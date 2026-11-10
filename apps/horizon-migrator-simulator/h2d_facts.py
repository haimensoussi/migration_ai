"""Extraction générique de faits (AST) sur une Action HORIZON.
Le code source n'est jamais importé ni exécuté : seule sa structure est lue.
(Copie de horizon2databricks/migrator/facts.py, embarquée dans l'App.)"""
from __future__ import annotations

import ast
import importlib.util
import re
import sys

# Modules internes à la plateforme source (complétés par la détection "non installé")
PLATFORM_HINTS = ("aistudio", "horizon", "apis", "logs", "utils")
URL_RE = re.compile(r"https?://[^\s'\"]+")


def _lit(node):
    try:
        return ast.literal_eval(node)
    except Exception:
        return None


def _classify(module: str) -> str:
    root = module.split(".")[0]
    if root in sys.stdlib_module_names:
        return "stdlib"
    if root in PLATFORM_HINTS:
        return "internal"
    try:
        return "third_party" if importlib.util.find_spec(root) is not None else "internal"
    except Exception:
        return "internal"


def extract_facts(source: str, filename: str = "action.py") -> dict:
    tree = ast.parse(source, filename=filename)

    imports: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                imports[a.name] = _classify(a.name)
        elif isinstance(n, ast.ImportFrom) and n.module:
            imports[n.module] = _classify(n.module)

    functions, entrypoints = [], []
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(n.name)
            for a in n.args.args:
                if a.annotation is not None and ast.unparse(a.annotation).split(".")[-1] == "RunContext":
                    entrypoints.append({"name": n.name, "context_param": a.arg,
                                        "async": isinstance(n, ast.AsyncFunctionDef), "line": n.lineno})

    constants = {}
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            v = _lit(n.value)
            if v is not None:
                constants[n.targets[0].id] = v

    ctx_names = {e["context_param"] for e in entrypoints} or {"context"}
    inputs, outputs, errors, http_calls, llm_calls = [], [], [], [], []
    context_attrs: set = set()
    seen_out = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in ctx_names:
            context_attrs.add(n.attr)
        if not isinstance(n, ast.Call):
            continue
        fname = ast.unparse(n.func)
        last = fname.split(".")[-1]
        kw = {k.arg: k.value for k in n.keywords if k.arg}
        if last == "get_input_value" and len(n.args) >= 2:
            v = _lit(n.args[1])
            if isinstance(v, str) and v not in inputs:
                inputs.append(v)
        elif last == "addValue" and n.args:
            name = _lit(n.args[0])
            if name not in seen_out:
                seen_out.add(name)
                outputs.append({"name": name, "type": _lit(kw["type"]) if "type" in kw else None, "line": n.lineno})
        elif last == "AppException":
            e = {k: (_lit(v) if _lit(v) is not None else ast.unparse(v)) for k, v in kw.items()}
            e["args"] = [_lit(a) if _lit(a) is not None else ast.unparse(a) for a in n.args]
            e["line"] = n.lineno
            errors.append(e)
        elif fname.split(".")[0] in ("requests", "httpx", "urllib") or last == "urlopen":
            url = None
            if n.args:
                url = _lit(n.args[0])
                if url is None and isinstance(n.args[0], ast.Name):
                    url = constants.get(n.args[0].id)  # URL définie dans une constante de module
            http_calls.append({"call": fname, "url": url, "line": n.lineno,
                               "kwargs": {k: ast.unparse(v) for k, v in kw.items()}})
        elif last in ("llm_call", "chat", "completion", "invoke", "generate"):
            llm_calls.append({"call": fname, "kwargs": sorted(kw), "line": n.lineno})
        elif fname == "getattr" and len(n.args) >= 2 and isinstance(n.args[0], ast.Name) and n.args[0].id in ctx_names:
            v = _lit(n.args[1])
            if isinstance(v, str):
                context_attrs.add(v)

    urls = sorted({m for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)
                   for m in URL_RE.findall(n.value)})
    return {
        "entrypoints": entrypoints,
        "functions": functions,
        "imports": imports,
        "internal_imports": sorted(m for m, c in imports.items() if c == "internal"),
        "third_party_imports": sorted(m for m, c in imports.items() if c == "third_party"),
        "constants": constants,
        "inputs": inputs,
        "outputs": outputs,
        "errors": errors,
        "error_codes": sorted({e.get("app_code") for e in errors if isinstance(e.get("app_code"), str)}),
        "llm_calls": llm_calls,
        "http_calls": http_calls,
        "urls": urls,
        "context_attributes": sorted(context_attrs),
        "insecure_tls": any(h["kwargs"].get("verify") == "False" for h in http_calls),
    }
