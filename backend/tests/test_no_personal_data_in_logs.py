"""No log line carries a channel payload, a phone or an address.

Política técnica inicial de dados de canais (proposta S10.1, D3, 16/09/2026):
logs com dado pessoal acidental vivem no máximo 14 dias, e **novos logs não
registram payload bruto, telefone ou endereço**. O prazo de log é do provedor de
hospedagem; o que é nosso é não escrever.

On 16/09/2026 the backend had ten logging and print calls, and none of them
passed any of this. This test keeps it that way: it reads every call to a
logger, to `logging`, to `print` and to `warnings.warn` from the syntax tree and
refuses one whose arguments name a payload, a body, a phone, an address or a
customer — as a variable, an attribute, a subscript key, a dict key or an
expression inside an f-string.

What it does not prove, said plainly: an exception message that happens to carry
data, logged as `exc` or through `logger.exception`, passes this scan. Channel
code must not build exception messages from payload content (S10.1, P9), and the
14-day ceiling on accidental logs exists for what slips past both.
"""

import ast
import re
import unicodedata
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical", "log"}

# Tokens, not substrings: "cep" must match `cep` and `delivery_cep`, never `exception`.
SENSITIVE_TOKENS = {
    "payload", "body",
    "phone", "telefone", "celular", "whatsapp",
    "address", "endereco", "logradouro", "cep", "postal",
    "customer", "cliente", "contact", "contato",
}


def _tokens(name: str) -> set[str]:
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", plain)
    return {part.lower() for part in re.split(r"[^A-Za-z0-9]+", spaced) if part}


def _is_log_call(node: ast.Call) -> bool:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id == "print"
    if isinstance(func, ast.Attribute):
        receiver = ast.unparse(func.value)
        if func.attr == "warn" and receiver == "warnings":
            return True
        return func.attr in LOG_METHODS and "log" in receiver.lower()
    return False


def _named_in(expression: ast.AST) -> set[str]:
    """Every name an argument reaches: variables, attributes, subscript and dict keys."""
    found = set()
    for node in ast.walk(expression):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            found.add(node.slice.value)
        elif isinstance(node, ast.Dict):
            found.update(
                key.value for key in node.keys
                if isinstance(key, ast.Constant) and isinstance(key.value, str)
            )
        elif isinstance(node, ast.keyword) and node.arg:
            found.add(node.arg)
    return found


def _leaks(root: Path) -> set[str]:
    offenders = set()
    for path in sorted(root.rglob("*.py")):
        # One file of the app starts with a BOM; the guard has to read it too.
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_log_call(node):
                continue
            names = set()
            for argument in [*node.args, *node.keywords]:
                names |= _named_in(argument)
            hits = sorted(name for name in names if _tokens(name) & SENSITIVE_TOKENS)
            if hits:
                offenders.add(f"{path.relative_to(root).as_posix()}:{node.lineno} -> {', '.join(hits)}")
    return offenders


def test_no_log_call_passes_a_payload_a_phone_an_address_or_a_customer():
    leaks = _leaks(APP)
    assert leaks == set(), (
        "Chamada de log ou print passando dado de canal ou pessoal:\n  "
        + "\n  ".join(sorted(leaks))
        + "\n\nRegistre identificadores (id do evento, do pedido, da conexão), nunca o conteúdo."
    )


PLANTED_LEAKS = """import logging
logger = logging.getLogger('x')
def f(payload, contato, data, cliente, valor_neutro, self):
    logger.info('pedido %s', payload)
    logging.warning(f'tel {contato.phone}')
    print(data['endereco'])
    self.log.error('falhou', extra={'customer': cliente})
    logger.info('x', extra={'phone': valor_neutro})
    logger.debug('cep=%s', data.deliveryCep)
"""

SAFE_CALLS = """import logging
logger = logging.getLogger('x')
def g(event, items, exc):
    logger.info('evento=%s pedido=%s', event.id, event.external_order_id)
    logger.exception('falhou id=%s: %s', event.id, exc)
    print(len(items))
    payload = {'nao': 'logado'}
"""


def test_the_guard_catches_what_it_exists_for_and_nothing_else(tmp_path):
    """The measure, broken on purpose: each planted leak is caught, each safe call is not."""
    (tmp_path / "vaza.py").write_text(PLANTED_LEAKS, encoding="utf-8")
    (tmp_path / "seguro.py").write_text(SAFE_CALLS, encoding="utf-8-sig")
    assert _leaks(tmp_path) == {
        "vaza.py:4 -> payload",
        "vaza.py:5 -> contato, phone",
        "vaza.py:6 -> endereco",
        "vaza.py:7 -> cliente, customer",
        "vaza.py:8 -> phone",
        "vaza.py:9 -> deliveryCep",
    }
