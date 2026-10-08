"""Chat client for the dashboard: one function, many servers, no key ever written or logged.

    chat(provider, base_url, model, api_key, messages) -> str

provider is one of the names in PROVIDERS. Four protocols sit behind them:

  local      a small instruct model run in this process with transformers (no server, no key;
             the default model downloads about 1 GB from the Hugging Face Hub on first use)
  ollama     POST {base_url}/api/chat
  openai     POST {base_url}/v1/chat/completions: LM Studio, llama.cpp, vLLM, and the hosted
             services that speak it (OpenAI, Gemini, Groq, OpenRouter, Mistral, DeepSeek)
  anthropic  the official anthropic SDK (pip install anthropic)

messages is the usual list of {"role": ..., "content": ...}. Every failure raises LLMError with
a plain message. An API key goes into the request header only; it is never printed, logged or
stored. The command-line test reads it from an environment variable you name, so it stays out
of the shell history:

    .venv/bin/python llm_client.py --list                       # Ollama's models
    .venv/bin/python llm_client.py --provider "Local (in-process)" "Say hello in five words"
    .venv/bin/python llm_client.py --provider Anthropic --api-key-env ANTHROPIC_API_KEY "hi"
    .venv/bin/python llm_client.py --provider Groq --api-key-env GROQ_API_KEY --model llama-3.3-70b-versatile "hi"
"""
import argparse
import json
import os
from collections.abc import Mapping
import socket
import sys
import urllib.error
import urllib.request

TIMEOUT = 60
LOCAL_DEFAULT_MODEL = "Qwen/Qwen2.5-0.5B-Instruct"
LOCAL_MAX_NEW_TOKENS = 300

PROVIDERS = {
    "Local (in-process)": {"protocol": "local", "url": "", "model": LOCAL_DEFAULT_MODEL, "key": "none",
                           "note": "runs inside this process on the CPU; no server, no key"},
    "Ollama (local)": {"protocol": "ollama", "url": "http://localhost:11434", "model": "", "key": "none",
                       "note": "ollama serve; pick a pulled model"},
    "OpenAI-compatible (LM Studio, llama.cpp, vLLM, ...)": {"protocol": "openai", "url": "http://localhost:1234",
                                                           "model": "", "key": "optional",
                                                           "note": "any server with /v1/chat/completions"},
    "OpenAI": {"protocol": "openai", "url": "https://api.openai.com/v1", "model": "gpt-4o-mini", "key": "required",
               "note": ""},
    "Anthropic": {"protocol": "anthropic", "url": "", "model": "claude-opus-5-5", "key": "required",
                  "note": "key from the box, or ANTHROPIC_API_KEY / an `ant auth login` profile when the box is empty"},
    "Google Gemini": {"protocol": "openai", "url": "https://generativelanguage.googleapis.com/v1beta/openai",
                      "model": "gemini-2.5-flash", "key": "required", "note": "Gemini's OpenAI-compatible endpoint"},
    "Groq": {"protocol": "openai", "url": "https://api.groq.com/openai/v1", "model": "llama-3.3-70b-versatile",
             "key": "required", "note": ""},
    "OpenRouter": {"protocol": "openai", "url": "https://openrouter.ai/api/v1", "model": "", "key": "required",
                   "note": "use Test connection to list models"},
    "Mistral": {"protocol": "openai", "url": "https://api.mistral.ai/v1", "model": "mistral-small-latest",
                "key": "required", "note": ""},
    "DeepSeek": {"protocol": "openai", "url": "https://api.deepseek.com/v1", "model": "deepseek-chat",
                 "key": "required", "note": ""},
}
_PATHS = {"ollama": {"chat": "/api/chat", "models": "/api/tags"},
          "openai": {"chat": "/v1/chat/completions", "models": "/v1/models"}}


class LLMError(Exception):
    """A failure talking to the model, with a message meant for the screen."""


def defaults(provider):
    """The provider's protocol, default URL and model, and whether it needs a key."""
    if provider not in PROVIDERS:
        raise LLMError(f"unknown provider {provider!r}; choose one of {list(PROVIDERS)}")
    return dict(PROVIDERS[provider])


def endpoint(provider, base_url, kind="chat"):
    """Full URL for a server provider's chat or models endpoint. A base URL that already ends in
    /v1 or /api is accepted as is."""
    spec = defaults(provider)
    if spec["protocol"] not in _PATHS:
        return spec["url"] or base_url or ""
    base = (base_url or spec["url"]).strip().rstrip("/")
    if not base.startswith(("http://", "https://")):
        base = "http://" + base
    path = _PATHS[spec["protocol"]][kind]
    for prefix in ("/v1", "/api"):
        if base.endswith(prefix) and path.startswith(prefix + "/"):
            path = path[len(prefix):]
    return base + path


def _check_messages(messages):
    if not messages or not all(isinstance(m, dict) and {"role", "content"} <= set(m) for m in messages):
        raise LLMError("messages must be a non-empty list of {'role': ..., 'content': ...}")
    return [{"role": m["role"], "content": m["content"]} for m in messages]


# ---------------------------------------------------------------- HTTP servers (ollama, openai)

def _error_text(body):
    try:
        parsed = json.loads(body)
        error = parsed.get("error", parsed) if isinstance(parsed, dict) else parsed
        if isinstance(error, dict):
            error = error.get("message", error)
        return str(error)[:300]
    except json.JSONDecodeError:
        return body[:300].strip() or "(empty body)"


def _request(url, payload=None, api_key=None, timeout=TIMEOUT):
    """GET (payload None) or POST JSON, returning the parsed JSON reply."""
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        raise LLMError(f"HTTP {error.code} from {url}: {_error_text(error.read().decode('utf-8', 'replace'))}") from None
    except urllib.error.URLError as error:
        if isinstance(error.reason, (socket.timeout, TimeoutError)) or "timed out" in str(error.reason):
            raise LLMError(f"no reply from {url} within {timeout} s") from None
        raise LLMError(f"cannot connect to {url}: {error.reason}. Is the server running?") from None
    except (socket.timeout, TimeoutError):
        raise LLMError(f"no reply from {url} within {timeout} s") from None
    except OSError as error:
        raise LLMError(f"connection to {url} failed: {error}") from None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        raise LLMError(f"reply from {url} is not JSON: {body[:200]!r}") from None


def _chat_server(provider, base_url, model, api_key, messages, timeout):
    protocol = defaults(provider)["protocol"]
    url = endpoint(provider, base_url, "chat")
    payload = {"model": model, "messages": messages}
    if protocol == "ollama":
        payload["stream"] = False
    reply = _request(url, payload, api_key, timeout)
    try:
        text = reply["message"]["content"] if protocol == "ollama" else reply["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise LLMError(f"unexpected reply shape from {url}: {json.dumps(reply)[:200]}") from None
    return text if isinstance(text, str) else ""


# ---------------------------------------------------------------- Anthropic (official SDK)

def _anthropic_client(base_url, api_key, timeout):
    try:
        import anthropic
    except ImportError:
        raise LLMError("the anthropic package is not installed: .venv/bin/pip install anthropic") from None
    kwargs = {"timeout": float(timeout), "max_retries": 1}
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url
    try:
        return anthropic, anthropic.Anthropic(**kwargs)
    except anthropic.AnthropicError as error:
        raise LLMError(f"Anthropic client: {error}") from None


def _anthropic_errors(anthropic, error, timeout):
    """Map the SDK's typed errors to LLMError, most specific first."""
    if isinstance(error, TypeError):   # the SDK raises a bare TypeError when it finds no credentials
        return LLMError("Anthropic needs an API key: the key box, ANTHROPIC_API_KEY, or an `ant auth login` profile")
    if isinstance(error, anthropic.AuthenticationError):
        return LLMError("Anthropic rejected the API key")
    if isinstance(error, anthropic.NotFoundError):
        return LLMError(f"Anthropic: {error.message}")
    if isinstance(error, anthropic.RateLimitError):
        return LLMError("Anthropic rate limit reached; try again in a moment")
    if isinstance(error, anthropic.APIStatusError):
        return LLMError(f"Anthropic returned {error.status_code}: {error.message}")
    if isinstance(error, anthropic.APITimeoutError):
        return LLMError(f"no reply from Anthropic within {timeout} s")
    if isinstance(error, anthropic.APIConnectionError):
        return LLMError(f"cannot connect to Anthropic: {error}")
    return LLMError(f"Anthropic: {error}")


def _chat_anthropic(base_url, model, api_key, messages, timeout):
    anthropic, client = _anthropic_client(base_url, api_key, timeout)
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [m for m in messages if m["role"] in ("user", "assistant")]
    if not turns or turns[0]["role"] != "user":
        raise LLMError("the first non-system message must come from the user")
    kwargs = {"model": model, "max_tokens": 4096, "messages": turns}
    if system:
        kwargs["system"] = system
    try:
        response = client.messages.create(**kwargs)
    except (anthropic.AnthropicError, TypeError) as error:
        raise _anthropic_errors(anthropic, error, timeout) from None
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        category = getattr(details, "category", None)
        return f"[the model declined to answer{': ' + category if category else ''}]"
    return "".join(block.text for block in response.content if block.type == "text")


# ---------------------------------------------------------------- Local (in-process, transformers)

_LOCAL = {}


def _local_model(name):
    if name not in _LOCAL:
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError:
            raise LLMError("torch and transformers are needed for the in-process model") from None
        try:
            tokenizer = AutoTokenizer.from_pretrained(name)
            net = AutoModelForCausalLM.from_pretrained(name, dtype=torch.float32)
        except (OSError, ValueError) as error:
            raise LLMError(f"cannot load {name!r}: {str(error)[:300]}") from None
        net.eval()
        _LOCAL[name] = (tokenizer, net)
    return _LOCAL[name]


def local_model_cached(name=LOCAL_DEFAULT_MODEL):
    """True when the model's files are already on disk (no download needed)."""
    try:
        from huggingface_hub import try_to_load_from_cache
    except ImportError:
        return False
    return all(isinstance(try_to_load_from_cache(name, file), str) for file in ("config.json", "model.safetensors"))


def _chat_local(model, messages, timeout):
    import torch
    tokenizer, net = _local_model(model or LOCAL_DEFAULT_MODEL)
    inputs = tokenizer.apply_chat_template(messages, add_generation_prompt=True, tokenize=True,
                                           return_tensors="pt", return_dict=True)
    if not isinstance(inputs, Mapping):      # older tokenizers return the tensor alone
        inputs = {"input_ids": inputs}
    inputs = dict(inputs)
    with torch.no_grad():
        output = net.generate(**inputs, max_new_tokens=LOCAL_MAX_NEW_TOKENS, do_sample=False,
                              max_time=float(timeout),
                              pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id)
    new_tokens = output[0, inputs["input_ids"].shape[1]:]
    return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()


# ---------------------------------------------------------------- public functions

def chat(provider, base_url, model, api_key, messages, timeout=TIMEOUT):
    """One chat completion, returned as text. Raises LLMError on any failure."""
    spec = defaults(provider)
    messages = _check_messages(messages)
    model = model or spec["model"]
    if not model:
        raise LLMError("no model name given")
    if spec["key"] == "required" and not api_key and spec["protocol"] != "anthropic":
        raise LLMError(f"{provider} needs an API key")
    if spec["protocol"] == "local":
        return _chat_local(model, messages, timeout)
    if spec["protocol"] == "anthropic":
        return _chat_anthropic(base_url, model, api_key, messages, timeout)
    return _chat_server(provider, base_url, model, api_key, messages, timeout)


def list_models(provider, base_url=None, api_key=None, timeout=TIMEOUT):
    """Model names the provider offers; for servers also the cheapest connection test."""
    spec = defaults(provider)
    if spec["protocol"] == "local":
        return [spec["model"]]
    if spec["protocol"] == "anthropic":
        anthropic, client = _anthropic_client(base_url, api_key, timeout)
        try:
            return [m.id for m in client.models.list()]
        except (anthropic.AnthropicError, TypeError) as error:
            raise _anthropic_errors(anthropic, error, timeout) from None
    url = endpoint(provider, base_url, "models")
    reply = _request(url, None, api_key, timeout)
    try:
        return [m["name"] for m in reply["models"]] if spec["protocol"] == "ollama" else [m["id"] for m in reply["data"]]
    except (KeyError, TypeError):
        raise LLMError(f"unexpected reply shape from {url}: {json.dumps(reply)[:200]}") from None


def test_connection(provider, base_url=None, model=None, api_key=None, timeout=TIMEOUT):
    """One line saying whether the provider is reachable and whether the model is known."""
    spec = defaults(provider)
    model = model or spec["model"]
    if spec["protocol"] == "local":
        cached = local_model_cached(model)
        return f"{model} is on disk, ready to load" if cached else f"{model} is not on disk yet: the first message downloads it (about 1 GB for the default)"
    models = list_models(provider, base_url, api_key, timeout)
    where = endpoint(provider, base_url, "models") or "Anthropic"
    if model and models and model not in models and not any(m.startswith(model) for m in models):
        return f"reachable ({len(models)} models at {where}) but {model!r} is not among them: {', '.join(models[:8])}"
    return f"reachable: {len(models)} models at {where}" + (f", {model!r} available" if model else "")


def main():
    parser = argparse.ArgumentParser(description="Send one chat message to a local or hosted model")
    parser.add_argument("prompt", nargs="?", help="the user message")
    parser.add_argument("--provider", default="Ollama (local)", choices=list(PROVIDERS))
    parser.add_argument("--base-url", default=None, help="server URL (default: the provider's)")
    parser.add_argument("--model", default=None, help="model name (default: the provider's)")
    parser.add_argument("--api-key-env", default=None, help="name of the environment variable holding the key")
    parser.add_argument("--system", default=None, help="optional system prompt")
    parser.add_argument("--timeout", type=float, default=TIMEOUT)
    parser.add_argument("--list", action="store_true", help="list the provider's models and exit")
    parser.add_argument("--test", action="store_true", help="test the connection and exit")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not api_key:
        sys.exit(f"error: environment variable {args.api_key_env} is empty or unset")
    try:
        if args.test:
            print(test_connection(args.provider, args.base_url, args.model, api_key, args.timeout))
            return
        if args.list:
            models = list_models(args.provider, args.base_url, api_key, args.timeout)
            print(f"{len(models)} model(s): {', '.join(models) or '-'}")
            return
        if not args.prompt:
            sys.exit("error: give a prompt, or --list / --test")
        model = args.model or defaults(args.provider)["model"]
        if not model:
            models = list_models(args.provider, args.base_url, api_key, args.timeout)
            if not models:
                sys.exit("error: the server lists no models; give --model")
            model = models[0]
        messages = ([{"role": "system", "content": args.system}] if args.system else []) + \
            [{"role": "user", "content": args.prompt}]
        print(f"[{args.provider}] model {model}" + (f" via {endpoint(args.provider, args.base_url)}" if endpoint(args.provider, args.base_url) else ""))
        print(chat(args.provider, args.base_url, model, api_key, messages, args.timeout))
    except LLMError as error:
        sys.exit(f"error: {error}")


if __name__ == "__main__":
    main()
