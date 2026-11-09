import unittest

import server


class ModelTuningTests(unittest.TestCase):
    def test_distill_uses_recommended_sampling_and_thinks_only_in_deep(self):
        for name in ("qwen3.8-9b-distill:q6_k", "hf.co/empero-ai/Qwen3.8-9B-Distill-GGUF:Q6_K"):
            for mode, profile in server.PROFILES.items():
                options, think = server.profile_request_settings(profile, model=name, output_tokens=-1)
                self.assertEqual(options["temperature"], 0.6, (name, mode))
                self.assertEqual(options["top_p"], 0.95)
                self.assertEqual(options["top_k"], 20)
                self.assertEqual(options["num_ctx"], profile["num_ctx"])
                # Only Deep mode spends time on a reasoning pass.
                self.assertEqual(think, mode == "deep", (name, mode))

    def test_default_27b_profiles_are_unchanged(self):
        for profile in server.PROFILES.values():
            options, think = server.profile_request_settings(profile, model="qwen3.8:27b", output_tokens=-1)
            self.assertEqual(options, {"temperature": profile["temperature"], "num_ctx": profile["num_ctx"], "num_predict": -1})
            self.assertEqual(think, profile["think"])


if __name__ == "__main__":
    unittest.main()
