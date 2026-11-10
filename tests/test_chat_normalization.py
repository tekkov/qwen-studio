import unittest

import server


class ChatNormalizationTests(unittest.TestCase):
    def roles(self, messages):
        return [item["role"] for item in messages]

    def test_mid_conversation_system_messages_merge_into_the_first(self):
        shaped = server.normalize_chat_messages([
            {"role": "system", "content": "Base prompt."},
            {"role": "system", "content": "Memory handoff."},
            {"role": "user", "content": "Fix the bug."},
            {"role": "system", "content": "Harness note."},
        ])
        self.assertEqual(self.roles(shaped), ["system", "user"])
        self.assertIn("Memory handoff.", shaped[0]["content"])
        self.assertIn("Harness note.", shaped[0]["content"])
        self.assertTrue(shaped[0]["content"].startswith("Base prompt."))

    def test_trimmed_request_is_restored_as_a_user_turn(self):
        shaped = server.normalize_chat_messages([
            {"role": "system", "content": "Base prompt."},
            {"role": "assistant", "content": "I read wallet.ts."},
        ], task_text="Review the wallet module")
        self.assertEqual(self.roles(shaped), ["system", "user", "assistant"])
        self.assertIn("Review the wallet module", shaped[1]["content"])

    def test_orphaned_tool_results_are_dropped(self):
        shaped = server.normalize_chat_messages([
            {"role": "system", "content": "Base prompt."},
            {"role": "tool", "content": "file contents"},
            {"role": "user", "content": "Continue."},
        ])
        self.assertEqual(self.roles(shaped), ["system", "user"])

    def test_well_formed_conversations_are_unchanged(self):
        messages = [
            {"role": "system", "content": "Base prompt."},
            {"role": "user", "content": "Read a file."},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "read_file", "arguments": {"path": "a"}}}]},
            {"role": "tool", "content": "data"},
        ]
        self.assertEqual(server.normalize_chat_messages(messages), messages)


if __name__ == "__main__":
    unittest.main()
