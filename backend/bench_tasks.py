"""R0 benchmark task suite — deterministic fixtures + checkers.

각 task = dict(code, category, complex, prompt, setup(d), check(d)->bool, fix(d)).
- setup: fixture 생성(격리된 임시 dir).
- check: 실제 결과물로 결정적 채점(테스트 실행·파일 내용·grep). LLM 판정 금지.
- fix: 정답을 적용하는 함수. benchmark 품질 검증에만 쓴다(LLM 무관):
    setup 직후 check==False(정답 노출·false positive 없음), fix 후 check==True(checker 유효).

prompt에 정답 코드를 직접 넣지 않는다(무엇을 원하는지만 자연어로).
"""
import json
import subprocess
import sys
from pathlib import Path


def run_py(d: Path, testfile: str) -> bool:
    """fixture 안 파이썬 테스트를 결정적으로 실행(exit 0 = 성공).
    에이전트/이전 실행이 남긴 stale 바이트코드가 채점을 오염시키지 않게 제거 후 실행."""
    for pyc in d.rglob("__pycache__"):
        for f in pyc.glob("*"):
            f.unlink()
    r = subprocess.run([sys.executable, "-B", testfile], cwd=str(d), capture_output=True, timeout=30)
    return r.returncode == 0


def W(d, name, text):
    (d / name).write_text(text, encoding="utf-8")


def R(d, name):
    return (d / name).read_text(encoding="utf-8", errors="replace")


# ───────────────────────────── task 정의 ─────────────────────────────
# 각 task는 setup/check/fix를 로컬 함수로 두고 아래 TASKS에 등록한다.

def _t_edit():
    def setup(d): W(d, "README.md", "# demo\n")
    def check(d): return "RUN=python main.py" in R(d, "README.md")
    def fix(d): W(d, "README.md", "# demo\nRUN=python main.py\n")
    return dict(code="A", category="단순 파일 수정", complex=False,
                prompt="README.md 파일의 맨 끝에 정확히 다음 한 줄을 추가해줘: RUN=python main.py",
                setup=setup, check=check, fix=fix)

def _t_bugfix():
    def setup(d):
        W(d, "calc.py", "def subtract(a, b):\n    return a + b\n")
        W(d, "test_calc.py", "from calc import subtract\nassert subtract(5, 3) == 2, subtract(5, 3)\nprint('ok')\n")
    def check(d): return run_py(d, "test_calc.py")
    def fix(d): W(d, "calc.py", "def subtract(a, b):\n    return a - b\n")
    return dict(code="B", category="단일 함수 bugfix", complex=False,
                prompt="test_calc.py가 통과하도록 calc.py의 subtract 함수를 고쳐줘. 지금 뺄셈이 아니라 덧셈을 한다.",
                setup=setup, check=check, fix=fix)

def _t_offbyone():
    def setup(d):
        W(d, "seq.py", "def first_n(xs, n):\n    return xs[:n - 1]\n")
        W(d, "test_seq.py", "from seq import first_n\nassert first_n([1,2,3,4], 2) == [1,2], first_n([1,2,3,4],2)\nprint('ok')\n")
    def check(d): return run_py(d, "test_seq.py")
    def fix(d): W(d, "seq.py", "def first_n(xs, n):\n    return xs[:n]\n")
    return dict(code="B2", category="off-by-one bugfix", complex=False,
                prompt="test_seq.py가 실패한다. seq.py의 first_n이 요소를 하나 적게 반환하는 버그를 찾아 고쳐줘.",
                setup=setup, check=check, fix=fix)

def _t_multifile_feature():
    def setup(d):
        W(d, "store.py", "_items = []\n\ndef add(x):\n    _items.append(x)\n\ndef items():\n    return list(_items)\n")
        W(d, "service.py", "import store\n\ndef delete(x):\n    pass  # TODO: store에서 x 제거\n")
        W(d, "test_app.py", "import store, service\nstore.add('a'); store.add('b')\nservice.delete('a')\nassert store.items() == ['b'], store.items()\nprint('ok')\n")
    def check(d): return run_py(d, "test_app.py")
    def fix(d):
        W(d, "store.py", "_items = []\n\ndef add(x):\n    _items.append(x)\n\ndef items():\n    return list(_items)\n\ndef remove(x):\n    _items.remove(x)\n")
        W(d, "service.py", "import store\n\ndef delete(x):\n    store.remove(x)\n")
    return dict(code="C", category="여러 파일 기능 추가", complex=True,
                prompt="test_app.py가 통과하도록 만들어줘. store에 항목 삭제 기능을 추가하고, service.delete가 그 삭제 기능을 호출하도록 연결해야 한다. 여러 파일을 수정해야 한다.",
                setup=setup, check=check, fix=fix)

def _t_multifile_bug():
    def setup(d):
        W(d, "money.py", "TAX = 0.1\n\ndef with_tax(p):\n    return p + p * TAX\n")
        W(d, "cart.py", "import money\n\ndef total(prices):\n    # 버그: 각 항목에 세금을 두 번 적용\n    return sum(money.with_tax(money.with_tax(p)) for p in prices)\n")
        W(d, "test_cart.py", "from cart import total\nassert abs(total([100, 200]) - 330.0) < 1e-6, total([100,200])\nprint('ok')\n")
    def check(d): return run_py(d, "test_cart.py")
    def fix(d): W(d, "cart.py", "import money\n\ndef total(prices):\n    return sum(money.with_tax(p) for p in prices)\n")
    return dict(code="D", category="여러 파일에 걸친 bugfix", complex=True,
                prompt="test_cart.py가 실패한다. 세금이 잘못 적용되는 버그를 찾아 고쳐줘. money.py와 cart.py를 살펴봐야 한다.",
                setup=setup, check=check, fix=fix)

def _t_explore_fix():
    def setup(d):
        (d / "pkg").mkdir()
        W(d / "pkg", "__init__.py", "")
        W(d / "pkg", "a.py", "def helper():\n    return 1\n")
        W(d / "pkg", "b.py", "def compute():\n    return 41  # 버그: 42여야 함\n")
        W(d / "pkg", "c.py", "def other():\n    return 'x'\n")
        W(d, "test_compute.py", "from pkg.b import compute\nassert compute() == 42, compute()\nprint('ok')\n")
    def check(d): return run_py(d, "test_compute.py")
    def fix(d): W(d / "pkg", "b.py", "def compute():\n    return 42\n")
    return dict(code="E", category="탐색 후 수정", complex=False,
                prompt="test_compute.py가 실패한다. pkg 안 어딘가에서 compute가 잘못된 값을 반환한다. 원인 파일을 찾아 고쳐줘.",
                setup=setup, check=check, fix=fix)

def _t_refactor():
    def setup(d):
        W(d, "geo.py", "def area(r):\n    return 3.14 * r * r\n\ndef circumference(r):\n    return 2 * 3.14 * r\n")
        W(d, "test_geo.py", "from geo import area, circumference\nassert abs(area(2) - 12.56) < 1e-6\nassert abs(circumference(2) - 12.56) < 1e-6\nprint('ok')\n")
    def check(d):
        # 리팩터: PI 상수로 묶고(3.14 리터럴 1개 이하), 테스트 통과
        src = R(d, "geo.py")
        return run_py(d, "test_geo.py") and src.count("3.14") <= 1 and "PI" in src
    def fix(d): W(d, "geo.py", "PI = 3.14\n\ndef area(r):\n    return PI * r * r\n\ndef circumference(r):\n    return 2 * PI * r\n")
    return dict(code="F", category="작은 refactoring", complex=False,
                prompt="geo.py의 두 함수가 3.14를 각각 하드코딩한다. 이 매직넘버를 PI라는 상수 하나로 묶어 재사용하도록 리팩터링해줘. 동작(테스트)은 그대로 유지되어야 한다.",
                setup=setup, check=check, fix=fix)

def _t_api_change():
    def setup(d):
        W(d, "greet.py", "def greet(name):\n    return 'Hi ' + name\n")
        W(d, "app.py", "from greet import greet\n\ndef welcome():\n    return greet('Sam')\n")
        W(d, "test_greet.py", "from greet import greet\nfrom app import welcome\nassert greet('Sam', lang='en') == 'Hi Sam'\nassert greet('Sam', lang='ko') == '안녕 Sam'\nassert welcome() == 'Hi Sam'\nprint('ok')\n")
    def check(d): return run_py(d, "test_greet.py")
    def fix(d):
        W(d, "greet.py", "def greet(name, lang='en'):\n    return ('안녕 ' if lang == 'ko' else 'Hi ') + name\n")
    return dict(code="G", category="API 변경에 따른 호출부", complex=True,
                prompt="greet 함수에 lang 인자를 추가해줘(기본값 'en', 'ko'이면 '안녕 '으로 인사). 기존 호출부(app.py의 welcome)는 그대로 동작해야 한다. test_greet.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix)

def _t_config():
    def setup(d): W(d, "config.json", json.dumps({"port": 3000, "debug": False}, indent=2))
    def check(d):
        try:
            c = json.loads(R(d, "config.json"))
            return c.get("port") == 8080 and c.get("debug") is False
        except Exception:
            return False
    def fix(d): W(d, "config.json", json.dumps({"port": 8080, "debug": False}, indent=2))
    return dict(code="H", category="configuration 수정", complex=False,
                prompt="config.json에서 port를 8080으로 바꿔줘. 나머지 설정은 그대로 둬.",
                setup=setup, check=check, fix=fix)

def _t_frontend():
    def setup(d): W(d, "index.html", "<!doctype html>\n<html><head><title>Old Title</title></head>\n<body><h1>Hello</h1></body></html>\n")
    def check(d):
        s = R(d, "index.html")
        return "<title>FORGE</title>" in s and "<h1>Hello</h1>" in s
    def fix(d): W(d, "index.html", "<!doctype html>\n<html><head><title>FORGE</title></head>\n<body><h1>Hello</h1></body></html>\n")
    return dict(code="I", category="frontend 수정", complex=False,
                prompt="index.html의 페이지 제목(title)을 'FORGE'로 바꿔줘. 본문(h1)은 건드리지 마.",
                setup=setup, check=check, fix=fix)

def _t_reuse_helper():
    def setup(d):
        W(d, "utils.py", "def slugify(s):\n    return s.strip().lower().replace(' ', '-')\n")
        W(d, "post.py", "# TODO: utils.slugify를 사용해 make_slug 구현\n")
        W(d, "test_post.py", "from post import make_slug\nimport post, utils\nassert make_slug(' Hello World ') == 'hello-world', make_slug(' Hello World ')\nprint('ok')\n")
    def check(d):
        # 정답: utils.slugify 재사용(재구현 금지). test 통과 + post.py가 utils를 참조.
        return run_py(d, "test_post.py") and "slugify" in R(d, "post.py") and "utils" in R(d, "post.py")
    def fix(d): W(d, "post.py", "import utils\n\ndef make_slug(s):\n    return utils.slugify(s)\n")
    return dict(code="J", category="기존 helper 재사용", complex=False,
                prompt="post.py에 make_slug 함수를 구현해줘. 문자열을 슬러그로 바꾸는 로직은 이미 utils.py에 있으니 새로 짜지 말고 그걸 재사용해. test_post.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix)

def _t_no_new_code():
    def setup(d):
        W(d, "log.py", "import logging\nlogger = logging.getLogger('app')\n\ndef run():\n    logger.info('started')\n    return 1\n")
        W(d, "test_log.py", "import log\nsrc = open('log.py').read()\nassert src.count(\"logger.info(\") == 1, src.count(\"logger.info(\")\nassert log.run() == 1\nprint('ok')\n")
    def check(d): return run_py(d, "test_log.py")
    def fix(d): pass  # 정답 = 변경 없음(이미 로깅 존재)
    def break_it(d):  # 잘못된 답(중복 로그 추가) → checker가 잡아야 함
        W(d, "log.py", "import logging\nlogger = logging.getLogger('app')\n\ndef run():\n    logger.info('started')\n    logger.info('started')\n    return 1\n")
    return dict(code="K", category="새 코드 작성이 정답이 아님(YAGNI)", complex=False, already_ok=True,
                prompt="log.py의 run 함수에 시작 로그를 남겨줘. 단 이미 시작 로그가 있으면 중복으로 추가하지 말고 그대로 둬.",
                setup=setup, check=check, fix=fix, break_it=break_it)

def _t_verify_assumption():
    def setup(d):
        W(d, "sorter.py", "def top3(xs):\n    return sorted(xs, reverse=True)[:3]\n")
        W(d, "test_sorter.py", "from sorter import top3\nassert top3([3,1,4,1,5,9,2]) == [9,5,4], top3([3,1,4,1,5,9,2])\nprint('ok')\n")
    def check(d): return run_py(d, "test_sorter.py")
    def fix(d): pass  # 정답 = 코드가 이미 맞음, 건드리지 않음
    def break_it(d): W(d, "sorter.py", "def top3(xs):\n    return sorted(xs)[:3]\n")  # 오름차순으로 깨뜨림
    return dict(code="L", category="잘못된 가정 검증", complex=False, already_ok=True,
                prompt="sorter.py의 top3가 내림차순 정렬을 안 하는 것 같다는 보고가 있어. 확인하고 문제가 있으면 고쳐줘. test_sorter.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix, break_it=break_it)

def _t_dead_code():
    def setup(d):
        W(d, "mod.py", "def used():\n    return 1\n\ndef unused_helper():\n    return 999\n\ndef main():\n    return used()\n")
        W(d, "test_mod.py", "import mod\nsrc = open('mod.py').read()\nassert 'unused_helper' not in src, 'dead code 남음'\nassert mod.main() == 1\nprint('ok')\n")
    def check(d): return run_py(d, "test_mod.py")
    def fix(d): W(d, "mod.py", "def used():\n    return 1\n\ndef main():\n    return used()\n")
    return dict(code="M", category="dead code 제거", complex=False,
                prompt="mod.py에서 아무 데서도 호출되지 않는 unused_helper 함수를 제거해줘. main과 used는 그대로 동작해야 한다.",
                setup=setup, check=check, fix=fix)

def _t_validation():
    def setup(d):
        W(d, "acct.py", "def withdraw(balance, amount):\n    return balance - amount\n")
        W(d, "test_acct.py", "from acct import withdraw\nassert withdraw(100, 30) == 70\ntry:\n    withdraw(100, 200)\n    assert False, '초과 인출이 막히지 않음'\nexcept ValueError:\n    pass\nprint('ok')\n")
    def check(d): return run_py(d, "test_acct.py")
    def fix(d): W(d, "acct.py", "def withdraw(balance, amount):\n    if amount > balance:\n        raise ValueError('잔액 부족')\n    return balance - amount\n")
    return dict(code="N", category="입력 검증 추가", complex=False,
                prompt="acct.py의 withdraw가 잔액보다 큰 금액도 그냥 음수로 반환한다. 잔액 초과 시 ValueError를 내도록 검증을 추가해줘. test_acct.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix)

def _t_multi_caller_const():
    def setup(d):
        for f in ("a.py", "b.py"):
            W(d, f, "from cfg import LIMIT\n\ndef use():\n    return LIMIT\n")
        W(d, "cfg.py", "LIMIT = 10\n")
        W(d, "test_limit.py", "import a, b\nfrom cfg import LIMIT\nassert LIMIT == 20\nassert a.use() == 20 and b.use() == 20\nprint('ok')\n")
    def check(d): return run_py(d, "test_limit.py")
    def fix(d): W(d, "cfg.py", "LIMIT = 20\n")
    return dict(code="O", category="여러 호출부 공유 상수", complex=False,
                prompt="cfg.py의 LIMIT을 20으로 바꿔줘. a.py, b.py가 이 값을 공유한다. test_limit.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix)

def _t_json_parse():
    def setup(d):
        W(d, "parse.py", "def get_name(raw):\n    # 버그: 통째로 반환\n    return raw\n")
        W(d, "test_parse.py", "import json\nfrom parse import get_name\nassert get_name('{\"name\": \"Kim\", \"age\": 3}') == 'Kim', get_name('{\"name\": \"Kim\"}')\nprint('ok')\n")
    def check(d): return run_py(d, "test_parse.py")
    def fix(d): W(d, "parse.py", "import json\n\ndef get_name(raw):\n    return json.loads(raw)['name']\n")
    return dict(code="P", category="JSON 파싱 수정", complex=False,
                prompt="parse.py의 get_name이 JSON 문자열에서 name 값만 뽑아야 하는데 통째로 반환한다. 고쳐줘. test_parse.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix)

def _t_complex_pipeline():
    def setup(d):
        W(d, "tokenize.py", "def tokens(s):\n    return s.split()\n")
        W(d, "count.py", "# TODO: word_freq 구현\n")
        W(d, "report.py", "# TODO: top_word 구현\n")
        W(d, "test_pipe.py",
          "from count import word_freq\nfrom report import top_word\n"
          "wf = word_freq('a b a c a b')\nassert wf == {'a':3,'b':2,'c':1}, wf\n"
          "assert top_word('a b a c a b') == 'a', top_word('a b a c a b')\nprint('ok')\n")
    def check(d): return run_py(d, "test_pipe.py")
    def fix(d):
        W(d, "count.py", "import tokenize\n\ndef word_freq(s):\n    f = {}\n    for t in tokenize.tokens(s):\n        f[t] = f.get(t, 0) + 1\n    return f\n")
        W(d, "report.py", "import count\n\ndef top_word(s):\n    wf = count.word_freq(s)\n    return max(wf, key=wf.get)\n")
    return dict(code="Q", category="COMPLEX 다단계 파이프라인", complex=True,
                prompt="여러 파일에 걸친 단어 빈도 파이프라인을 완성해줘. count.py에 word_freq(문자열→{단어:횟수})를, report.py에 top_word(가장 많이 나온 단어)를 구현하고, 기존 tokenize.tokens를 재사용해. test_pipe.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix)

def _t_complex_statemachine():
    def setup(d):
        W(d, "light.py", "# TODO: TrafficLight 구현 (green->yellow->red->green)\n")
        W(d, "test_light.py",
          "from light import TrafficLight\nt = TrafficLight()\n"
          "assert t.state == 'green'\nt.next(); assert t.state == 'yellow'\n"
          "t.next(); assert t.state == 'red'\nt.next(); assert t.state == 'green'\nprint('ok')\n")
    def check(d): return run_py(d, "test_light.py")
    def fix(d):
        W(d, "light.py",
          "class TrafficLight:\n    _order = ['green', 'yellow', 'red']\n    def __init__(self):\n        self.state = 'green'\n"
          "    def next(self):\n        i = self._order.index(self.state)\n        self.state = self._order[(i + 1) % 3]\n")
    return dict(code="R", category="COMPLEX 상태머신 설계", complex=True,
                prompt="light.py에 TrafficLight 클래스를 구현해줘. 초기 상태는 green이고 next()를 호출할 때마다 green→yellow→red→green 순으로 순환해야 한다. test_light.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix)

def _t_import_fix():
    def setup(d):
        W(d, "helpers.py", "def double(x):\n    return x * 2\n")
        W(d, "run.py", "from helpers import triple\n\ndef go():\n    return triple(5)\n")  # 잘못된 import
        W(d, "test_run.py", "from run import go\nassert go() == 10, go()\nprint('ok')\n")
    def check(d): return run_py(d, "test_run.py")
    def fix(d): W(d, "run.py", "from helpers import double\n\ndef go():\n    return double(5)\n")
    return dict(code="S", category="잘못된 import 수정", complex=False,
                prompt="test_run.py가 ImportError로 실패한다. run.py가 helpers에 없는 함수를 import한다. 올바른 함수를 쓰도록 고쳐줘(결과는 10이어야 함).",
                setup=setup, check=check, fix=fix)

def _t_bugfix_recursion():
    def setup(d):
        W(d, "fact.py", "def fact(n):\n    if n == 0:\n        return 0  # 버그: 1이어야 함\n    return n * fact(n - 1)\n")
        W(d, "test_fact.py", "from fact import fact\nassert fact(5) == 120, fact(5)\nassert fact(0) == 1\nprint('ok')\n")
    def check(d): return run_py(d, "test_fact.py")
    def fix(d): W(d, "fact.py", "def fact(n):\n    if n == 0:\n        return 1\n    return n * fact(n - 1)\n")
    return dict(code="T", category="재귀 base case bugfix", complex=False,
                prompt="fact.py의 팩토리얼이 항상 0을 반환한다. base case 버그를 찾아 고쳐줘. test_fact.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix)


def _t_failing_test_debug():
    """failing-test debugging: 실패하는 테스트를 예외 traceback을 따라가며 원인을 찾는 디버깅."""
    def setup(d):
        W(d, "parse.py", "def to_int(s):\n    return int(s)\n")
        W(d, "process.py",
          "import parse\n\ndef total(rows):\n    return sum(parse.to_int(r) for r in rows)\n")
        W(d, "test_process.py",
          "from process import total\n"
          "assert total(['1', '2', '3']) == 6, total(['1','2','3'])\n"
          "assert total(['1', 'x', '3']) == 4, total(['1','x','3'])  # 'x'는 건너뛰어야 함\n"
          "print('ok')\n")
    def check(d): return run_py(d, "test_process.py")
    def fix(d):
        W(d, "process.py",
          "import parse\n\ndef total(rows):\n    s = 0\n    for r in rows:\n        try:\n            s += parse.to_int(r)\n        except ValueError:\n            pass\n    return s\n")
    return dict(code="U", category="failing-test 디버깅(예외 경로 추적)", complex=True,
                prompt="test_process.py가 ValueError로 실패한다. process.total이 숫자가 아닌 문자열을 만나면 예외를 던진다. 숫자로 변환 가능한 값만 합산하고 나머지는 건너뛰도록 고쳐줘. test_process.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix)


def _t_ambiguous_requirement():
    """ambiguous requirement: 요구사항이 모호하고, 정확한 규칙은 테스트로만 드러난다."""
    def setup(d):
        W(d, "clean.py", "def clean(s):\n    return s\n")
        W(d, "test_clean.py",
          "from clean import clean\n"
          "assert clean('  Hello  World  ') == 'hello world', clean('  Hello  World  ')\n"
          "assert clean('A!B@C#') == 'abc', clean('A!B@C#')\n"
          "assert clean('') == '', clean('')\n"
          "print('ok')\n")
    def check(d): return run_py(d, "test_clean.py")
    def fix(d):
        W(d, "clean.py", "import re\n\ndef clean(s):\n    return re.sub(r'\\s+', ' ', re.sub(r'[^a-z0-9 ]', '', s.lower())).strip()\n")
    return dict(code="V", category="모호한 요구사항(테스트로 규칙 파악)", complex=False,
                prompt="clean 함수를 구현해줘. 문자열을 '정리'하는 함수인데 정확한 규칙은 명시하지 않겠다. test_clean.py를 읽고 어떤 규칙을 기대하는지 파악해서 그대로 구현해줘.",
                setup=setup, check=check, fix=fix)


def _t_long_running_restart():
    """long-running/restart: 상태를 파일에 영속화하고 재실행 시 이어간다."""
    def setup(d):
        W(d, "counter.py",
          "import json\nfrom pathlib import Path\n\n"
          "STATE = Path('state.json')\n\n"
          "def load():\n"
          "    # TODO: state.json에서 count 읽기(없으면 0)\n"
          "    return 0\n\n"
          "def bump():\n"
          "    # TODO: count를 1 올리고 state.json에 저장\n"
          "    return load() + 1\n")
        W(d, "test_counter.py",
          "import counter\n"
          "assert counter.bump() == 1, counter.bump()\n"
          "assert counter.bump() == 2, counter.bump()\n"
          "print('ok')\n")
    def check(d):
        # FORGE의 검증 단계가 test_counter.py를 돌리면 state.json에 count가 남아, 같은
        # 테스트를 다시 실행하는 checker에서 bump()==1이 깨진다(비멱등 → 거짓 false_completion).
        # checker는 "fresh 프로세스 시작"을 재므로 잔존 상태를 지우고 실행한다.
        (d / "state.json").unlink(missing_ok=True)
        return run_py(d, "test_counter.py")
    def fix(d):
        W(d, "counter.py",
          "import json\nfrom pathlib import Path\n\n"
          "STATE = Path('state.json')\n\n"
          "def load():\n"
          "    if STATE.exists():\n"
          "        return json.loads(STATE.read_text()).get('count', 0)\n"
          "    return 0\n\n"
          "def bump():\n"
          "    n = load() + 1\n"
          "    STATE.write_text(json.dumps({'count': n}))\n"
          "    return n\n")
    return dict(code="W", category="long-running 상태 영속화", complex=True,
                prompt="counter.py의 bump가 호출될 때마다 1씩 증가하는 카운터를 구현해줘. 단, 카운트는 state.json 파일에 저장되어 프로세스가 재시작돼도 이어져야 한다(메모리 변수만으로는 안 됨). test_counter.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix)


def _t_frontend_backend_integration():
    """frontend/backend 통합: HTML 폼과 JS 검증 로직이 함께 동작해야 한다."""
    def setup(d):
        W(d, "index.html",
          "<!doctype html>\n<html><head><title>Form</title></head>\n<body>\n"
          "<form id='f'><input id='email'><button>submit</button></form>\n"
          "<script src='validate.js'></script>\n"
          "</body></html>\n")
        W(d, "validate.js", "// TODO: validateEmail 구현\n")
        W(d, "test_validate.py",
          "import re\n"
          "src = open('validate.js').read()\n"
          "assert 'validateEmail' in src, 'validateEmail 함수 없음'\n"
          "assert 'includes' in src or 'indexOf' in src, '이메일 검증 로직 없음'\n"
          "print('ok')\n")
    def check(d): return run_py(d, "test_validate.py")
    def fix(d):
        W(d, "validate.js",
          "function validateEmail(e) {\n"
          "  return e.includes('@') && e.includes('.');\n"
          "}\n")
    return dict(code="X", category="frontend/backend 통합", complex=False,
                prompt="index.html의 폼에서 이메일을 검증하려고 한다. validate.js에 validateEmail 함수를 구현해줘. 이메일 형식(@와 . 포함)을 검사하는 함수다. test_validate.py가 통과해야 한다.",
                setup=setup, check=check, fix=fix)


TASKS = [
    _t_edit(), _t_bugfix(), _t_offbyone(), _t_multifile_feature(), _t_multifile_bug(),
    _t_explore_fix(), _t_refactor(), _t_api_change(), _t_config(), _t_frontend(),
    _t_reuse_helper(), _t_no_new_code(), _t_verify_assumption(), _t_dead_code(),
    _t_validation(), _t_multi_caller_const(), _t_json_parse(), _t_complex_pipeline(),
    _t_complex_statemachine(), _t_import_fix(), _t_bugfix_recursion(),
    _t_failing_test_debug(), _t_ambiguous_requirement(), _t_long_running_restart(),
    _t_frontend_backend_integration(),
]
