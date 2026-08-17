# Testing and benchmarks

Run deterministic tests and syntax checks with `npm run check`. The suite covers artifact enforcement, plain chat completion, project/thread/attachment APIs, persistent thread messages, text/image Ollama payload preparation, and context trimming.

Run the optional real-model tool test with Ollama running:

```powershell
npm run smoke:model
```

This creates an isolated temporary workspace, asks the real model to write and read a file, verifies the exact contents, and removes the workspace.

## Audited local performance

On an RTX 5060 8 GB, 32 GB RAM, and Core Ultra 5 225F, the installed 27.3B Q4 model uses both CPU and GPU. A real vision smoke test generated 23 tokens at 4.03 TPS. A warm real coding-agent file-write/read loop completed in 54.9 seconds with ten visible run events. Performance varies with prompt length, context, thermal state, and how much of the model fits in VRAM.

The app reports model-supplied generation TPS and prompt-processing speed after a run. First response latency is recorded when Ollama emits its first stream chunk.
