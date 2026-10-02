"""핵심 로직 단위 테스트 (API 호출 없이 실행 가능).

실행: python -m unittest discover -s tests -v
"""

import unittest

from gitgen import formatter, safe_mode
from gitgen.ai_client import AIError, parse_json_response


class TestSafeMode(unittest.TestCase):
    def test_masks_keys_and_personal_info(self):
        diff = (
            "diff --git a/config.py b/config.py\n"
            '+OPENAI_KEY = "sk-proj-abcdefghijklmnopqrstuvwxyz123456"\n'
            "+admin = 'hong@example.com'\n"
            "+phone = '010-1234-5678'\n"
            '+password = "hunter2pass"\n'
        )
        out, rep = safe_mode.apply_safe_mode(diff, max_files=10, max_lines=200)
        self.assertNotIn("sk-proj-abcdef", out)
        self.assertNotIn("hong@example.com", out)
        self.assertNotIn("010-1234-5678", out)
        self.assertNotIn("hunter2pass", out)
        self.assertGreaterEqual(rep.masked_total, 4)

    def test_placeholders_and_code_not_masked(self):
        diff = (
            "diff --git a/a.py b/a.py\n"
            '+export AI_API_KEY="YOUR_KEY"\n'
            "+    api_key = get_api_key()\n"
            '+token = "sk-..."\n'
        )
        out, rep = safe_mode.apply_safe_mode(diff, 10, 200)
        self.assertIn("YOUR_KEY", out)
        self.assertIn("get_api_key()", out)
        self.assertEqual(rep.masked_total, 0)

    def test_excludes_env_file(self):
        diff = "diff --git a/.env b/.env\n+AI_API_KEY=abc123secret\n"
        out, rep = safe_mode.apply_safe_mode(diff, 10, 200)
        self.assertIn(".env", rep.excluded_files)
        self.assertNotIn("abc123secret", out)

    def test_limits_files_and_lines(self):
        diff = "\n".join(f"diff --git a/f{i}.py b/f{i}.py\n+line" for i in range(15))
        out, rep = safe_mode.apply_safe_mode(diff, max_files=10, max_lines=200)
        self.assertEqual(len(rep.dropped_files), 5)
        big = "diff --git a/a.py b/a.py\n" + "\n".join(f"+x{i}" for i in range(500))
        out, rep = safe_mode.apply_safe_mode(big, 10, 200)
        self.assertTrue(rep.truncated_by_lines)
        self.assertLessEqual(len(out.splitlines()), 201)


class TestFormatter(unittest.TestCase):
    def test_commit_title_truncated_to_72(self):
        c = formatter.check_commit({"title": "feat: " + "아주 긴 제목 " * 20, "body_bullets": ["a"]})
        self.assertLessEqual(len(c.title), 72)
        self.assertTrue(any(level == "FIX" for level, _ in c.checks))

    def test_commit_title_cleanup(self):
        c = formatter.check_commit({"title": "fix: 오류 수정.\n두번째 줄", "body_bullets": ["- main.py 수정"]})
        self.assertEqual(c.title, "fix: 오류 수정")
        self.assertEqual(c.body, "- main.py 수정")

    def test_pr_sections_always_present(self):
        c = formatter.check_pr({"title": "feat: x", "why": [], "what": ["a"], "how_to_test": None})
        ok, _ = formatter.validate_pr_body(c.body)
        self.assertTrue(ok)
        for h in ("## Why", "## What", "## How to Test"):
            self.assertIn(h, c.body)

    def test_pr_title_max_80(self):
        c = formatter.check_pr({"title": "feat: " + "x" * 200, "why": ["a"], "what": ["b"], "how_to_test": ["c"]})
        self.assertLessEqual(len(c.title), 80)


class TestJsonParse(unittest.TestCase):
    def test_code_fence(self):
        self.assertEqual(parse_json_response('```json\n{"title": "t"}\n```')["title"], "t")

    def test_invalid(self):
        with self.assertRaises(AIError):
            parse_json_response("not json")


if __name__ == "__main__":
    unittest.main()
