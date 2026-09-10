#!/usr/bin/env python3
"""web_driver.py — 「値の正本 → 画面に打つ操作列」 を決定的に生成する site 非依存 harness
(規約 = ``web-form-automation.md#step-driver-harness``)。

経路 ladder (``machine-route-first.md#route-ladder``) の **最下段**、 すなわち公式 API も CLI も
内部 endpoint replay も使えない web app (レガシー JSP / frameset / 行政ポータル) を、 それでも
GUI click ではなく機械で駆動するための土台。 **上位段が使えるならここへ降りてこない** —
経路の選択は #route-ladder が先で、 本 module はその判定の結果として選ばれる。

## 思想 (3 層)

  A. 値の正本 (site 側の yaml 等)      … 画面を正本にしない。 これの無い自動化は「速く間違える」 だけ
  B. 操作列 = steps (本 module)        … SoT → ``[{label, js, wait, expect, human}]`` を決定的に出す
  C. 読み戻し照合 (site 側の parser)   … 打った後に画面を読み、 SoT と全項目 diff してから人間へ渡す

本 module は B の骨格と、 C の入力になる readback JS を提供する。 **Python はブラウザに触らない** —
生成した steps を agent が browser tool (Claude 内蔵 Browser pane の ``javascript_tool`` 等) に順に流し、
各 step の ``expect`` と照合する。 これにより「値を頭から出す」 のではなく「正本から出した操作列を流す」
形になり、 再実行・差分確認・selftest が可能になる。

## site 側が書くもの (= サイトごとに 1 回の実測台帳)

    from web_driver import Ctx, step, render_md, audit_steps

    ctx = Ctx(frame="window.frames[1]", form="shinsei_form")   # frameset の main。 素の page なら Ctx()
    steps = [
        step("ログイン", human="pane を表示して user が ID/PW を打つ (agent は打たない)"),
        step("メニューへ", js=ctx.js_nav("/app/menu.do"), wait=4),
        step("画面 01", js=ctx.js_call("onInput('01')", ret="01"), wait=4),
        ctx.fill({"a.b.c": "値"}, dispatch=["a.b.c"]),
        step("一時保存", js=ctx.js_call("onSave()", ret="save"), wait=4),
        ctx.readback(r"研究課題名.{0,160}"),
    ]

field 名・保存関数名・画面遷移は **サイトごとに 1 回実測して literal で docstring に残す**。
採取用の probe = ``ctx.js_frame_probe()`` / ``ctx.js_field_dump()`` / ``ctx.js_handler_dump()`` / ``js_capture_xhr()``
(まとめて出すなら ``python3 web_driver.py --probe --url <URL>`` = 新サイト着手の 1 コマンド)。

## どのサイトでも効く罠 (実測由来)

- **server 往復の後は待つ**: 画面の保存 / 行追加関数は lockButton + ``setTimeout`` で submit することが多く、
  連続呼びは 2 回目以降が黙って捨てられる。 往復 step には必ず ``wait`` (``audit_steps`` が欠落を検出)。
- **返り値に生 HTML を混ぜない**: browser tool の出力 filter は cookie / query string 風の文字列
  (``=`` ``&`` ``;`` の並び、 href 群) を見ると結果全体を ``[BLOCKED]`` に潰す
  (``web-tools.md#javascript-tool-gotchas``)。 helper は名前・件数・短文だけを返す。
- **element が無い時は throw せず ``missing`` で返す**: 種目差・年度差・様式改訂は「無い field」 として
  現れる。 例外にすると step 列が途中で死に、 原因が読めない。 ``missing`` なら次の実行で SoT に足せる。
- **「保存できた」 を応答画面で判断しない**: 成否は readback の本文と、 可能ならサーバ側の一覧で確認する
  (``web-form-automation.md#submit-truth-is-server-state``)。
- **async IIFE は ``{}`` に潰れる**: 戻り値が要る JS は同期式にする (同 #javascript-tool-gotchas)。
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

# readback がエラーとして拾う語 (日本語の行政・学術ポータル既定。 site 側で差し替え可)
DEFAULT_ERROR_WORDS = ("エラー", "できません", "不正", "バイト以内", "文字以内")
DEFAULT_ERROR_IGNORE = "メッセージが出た"
# js に含まれていたら server 往復とみなす marker (= wait 必須)
ROUNDTRIP_MARKERS = (".submit(", ".click(", ".eval(", "location.href=", "location=")


def J(x) -> str:
    """JS に埋める JSON (非 ASCII は \\uXXXX に逃がす = tool 経由の encoding 事故を避ける)。"""
    return json.dumps(x, ensure_ascii=True)


def step(label: str, js: str | None = None, wait: float | None = None,
         expect: dict | None = None, human: str | None = None) -> dict:
    """1 step = 1 tool call。 js / wait / human のいずれかは要る。"""
    d: dict = {"label": label}
    if js:
        d["js"] = js
    if wait:
        d["wait"] = wait
    if expect is not None:
        d["expect"] = expect
    if human:
        d["human"] = human
    return d


@dataclass
class Ctx:
    """操作対象の window / form を固定した JS 生成器。

    frame … 対象 window の JS 式。 frameset なら ``window.frames[1]``、 素の page なら ``window``
    form  … ``document.<form>`` の name。 None なら name / id で element を引く (SPA・素の form)
    wait  … server 往復 step の既定待ち秒 (呼び出し側が個別に上書き可)
    """

    frame: str = "window"
    form: str | None = None
    wait: float = 4.0

    # ---------------------------------------------------------------- 内部
    def _elem(self) -> tuple[str, str]:
        """(prologue, element 取得式 〔変数 n を使う〕)。"""
        if self.form:
            return ("const f=" + self.frame + ";const fm=f.document." + self.form + ";", "fm.elements[n]")
        return ("const f=" + self.frame + ";const D0=f.document;",
                "(D0.querySelector('[name=\"'+n+'\"]')||D0.getElementById(n))")

    @staticmethod
    def _norm_fn() -> str:
        """画面の option label と SoT 表記の差 (全角/半角括弧・空白) を吸収する正規化関数 N。"""
        return "const N=s=>String(s).replace(/[（(]/g,'(').replace(/[）)]/g,')').replace(/[\\s\\u3000]/g,'');"

    # ---------------------------------------------------------------- 遷移・呼び出し
    def js_nav(self, path: str, ret: str = "nav") -> str:
        """frame をその path / URL へ飛ばす (= server 往復 → wait が要る)。"""
        return "(()=>{" + self.frame + ".location.href=" + J(path) + ";return " + J(ret) + "})()"

    def js_call(self, expr: str, ret: str = "call") -> str:
        """page 内の関数を呼ぶ。 expr は frame 起点の literal (例 ``onInputApplication('01')``)。"""
        return "(()=>{" + self.frame + "." + expr + ";return " + J(ret) + "})()"

    def js_call_href(self, fn_pattern: str, ret: str = "call-href", literal: bool = False) -> str:
        """``<a href="javascript:onFoo('x')">`` を探して href をそのまま eval する (引数付き保存関数の定石)。

        literal=True … pattern を **部分文字列** として照合する。 特定行の handler を狙うとき
        (``onUpdate('20260908231617499'`` 等) は引数に ``(`` ``'`` が入って正規表現として壊れるので必須。
        ⚠️ 見つからない時は throw せず ``{missing: <pattern>}`` を返す。
        """
        if literal:
            find = "e=>(e.getAttribute('href')||'').includes(" + J(fn_pattern) + ")"
        else:
            find = "e=>new RegExp(" + J(fn_pattern) + ").test(e.getAttribute('href')||'')"
        return ("(()=>{const f=" + self.frame + ";const a=Array.from(f.document.querySelectorAll('a'))"
                ".find(" + find + ");"
                "if(!a)return {missing:" + J(fn_pattern) + "};"
                "f.eval(a.getAttribute('href').replace(/^javascript:/,''));return " + J(ret) + "})()")

    def js_click(self, fn_pattern: str, ret: str = "click", literal: bool = False) -> str:
        """onclick / href が pattern に一致する ``<a>`` を click (行追加ボタン等)。

        literal=True … 部分文字列で照合 (引数付き handler を狙うとき。 js_call_href と同じ理由)。
        """
        test = ("h.includes(" + J(fn_pattern) + ")" if literal
                else "new RegExp(" + J(fn_pattern) + ").test(h)")
        return ("(()=>{const d=" + self.frame + ".document;const a=Array.from(d.querySelectorAll('a'))"
                ".find(e=>{const h=e.getAttribute('onclick')||e.getAttribute('href')||'';return " + test + ";});"
                "if(!a)return {missing:" + J(fn_pattern) + "};a.click();return " + J(ret) + "})()")

    # ---------------------------------------------------------------- 入力
    def js_fill(self, values: dict, dispatch=()) -> str:
        """``{field 名: 値}`` を一括代入。 dispatch に挙げた name は change を飛ばす (連動 select 用)。

        返り値 = ``{set: 件数, missing: [無かった name]}``。 **無い name で throw しない**。
        """
        pro, get = self._elem()
        return ("(()=>{" + pro + "const V=" + J(values) + ";const D=" + J(list(dispatch)) +
                ";const set=[],missing=[];for(const n in V){const e=" + get + ";if(!e){missing.push(n);continue;}e.value=V[n];"
                "if(D.includes(n)){e.dispatchEvent(new f.Event('change',{bubbles:true}));}set.push(n);}"
                "return {set:set.length,missing};})()")

    def js_select_by_label(self, name: str, label: str) -> str:
        """select を **表示文字列** で選ぶ (value は画面内部 code のことが多く SoT に書けないため)。

        一致しない時は ``{nomatch, options}`` を返す = 台帳を直す材料がその場で出る。
        """
        pro, get = self._elem()
        return ("(()=>{" + pro + self._norm_fn() + "const n=" + J(name) + ";const e=" + get + ";"
                "if(!e)return {missing:n};const t=N(" + J(label) + ");"
                "const o=Array.from(e.options).find(o=>N(o.value)===t||N(o.text)===t);"
                "if(!o)return {nomatch:" + J(label) + ",options:Array.from(e.options).map(o=>o.text)};"
                "e.value=o.value;return {ok:o.value};})()")

    # ---------------------------------------------------------------- 読み
    def js_readback(self, pattern: str = "", saved: str = "", words=DEFAULT_ERROR_WORDS,
                    ignore: str = DEFAULT_ERROR_IGNORE) -> str:
        """本文を 1 行に潰して (a) 保存成功文言 (b) 正規表現 hit (c) エラー語 を同時に取る。

        画面遷移の成否・保存の成否・validation エラーは **1 回の読みで同時に判定する** —
        別々に読むと「保存は通ったがエラーも出ていた」 を取り落とす。
        """
        w = "(" + "|".join(words) + ")[^。]{0,80}"
        js = ("(()=>{const f=" + self.frame + ";const c=f.document.body.innerText.replace(/\\s+/g,' ');"
              "const m=c.match(new RegExp(" + J(pattern) + "));"
              "return {path:f.location.pathname,saved:c.includes(" + J(saved) + "),hit:m?m[0]:null,"
              "errs:(c.match(/" + w + "/g)||[])")
        if ignore:
            js += ".filter(s=>!/" + ignore + "/.test(s))"
        return js + ".slice(0,6)};})()"

    def js_text(self) -> str:
        """本文全文を採取 (site 側 parser / fixture 用)。"""
        return "(()=>{const f=" + self.frame + ";return {path:f.location.pathname,text:f.document.body.innerText}})()"

    # ---------------------------------------------------------------- 台帳採取 probe
    def js_field_dump(self, limit: int = 400) -> str:
        """form の全 element を ``name:TAG/type[option 数]`` で列挙 (= field 名台帳の採取)。

        ⚠️ 値は返さない (個人情報と出力 filter の両方を避ける)。 name 内の ``=&;`` は ``_`` に潰す。
        """
        pro = ("const f=" + self.frame + ";const fm=f.document." + self.form + ";const L=fm?fm.elements:[];"
               if self.form else
               "const f=" + self.frame + ";const L=f.document.querySelectorAll('input,select,textarea');")
        return ("(()=>{" + pro + "const S=x=>String(x||'?').replace(/[=&;]/g,'_');const out=[];"
                "for(const e of L){out.push(S(e.name||e.id)+':'+e.tagName+(e.type?'/'+e.type:'')+"
                "(e.tagName==='SELECT'?'['+e.options.length+']':''));}"
                "return {n:out.length,names:out.slice(0," + str(limit) + ")};})()")

    def js_frame_probe(self) -> str:
        """frameset か否かと、 各 frame の path / 本文長 / form 名を返す (= main frame の同定)。

        レガシー web app で最初にぶつかる壁がこれ — frameset だと `get_page_text` が空を返し、
        「読めないサイト」 に見える。 本 probe で main の index が分かれば Ctx(frame=...) が決まる。
        """
        return ("(()=>{const W=window;const out=[];const n=W.frames.length;"
                "for(let i=0;i<n;i++){try{const d=W.frames[i].document;"
                "out.push({i,path:d.location.pathname,len:(d.body?d.body.innerText.length:0),"
                "forms:Array.from(d.forms||[]).map(f=>String(f.name||f.id||'?')).slice(0,8)});}"
                "catch(e){out.push({i,err:'cross-origin'});}}"
                "let top={};try{top={path:W.document.location.pathname,"
                "len:(W.document.body?W.document.body.innerText.length:0)};}catch(e){top={err:String(e.name)};}"
                "return {frameset:n>0,n,frames:out,top};})()")

    def js_handler_dump(self, limit: int = 120) -> str:
        """page 内の ``a[onclick|href=javascript:]`` から **関数名だけ** を重複なく抜く (= 画面 API の採取)。

        href 全文は返さない (query string 風で出力 filter に潰されるため)。
        """
        return ("(()=>{const d=" + self.frame + ".document;const s=new Set();"
                "for(const a of d.querySelectorAll('a,input[type=button],button')){"
                "const h=(a.getAttribute('onclick')||'')+' '+(a.getAttribute('href')||'');"
                "for(const m of h.matchAll(/([A-Za-z_$][\\w$]{2,})\\s*\\(/g))s.add(m[1]);}"
                "return {n:s.size,fns:Array.from(s).slice(0," + str(limit) + ")};})()")


def js_capture_xhr(seconds: int = 60) -> str:
    """XHR / fetch を一時 hook して **実 UI 操作 1 回分** の method / URL / field 名を捕捉する。

    ``machine-route-first.md#internal-endpoint-replay`` の step 1 (= 推測で endpoint を組まない)。
    捕捉後に ``js_capture_xhr_read()`` で読む。 ⚠️ header 値・body 値は返さない (secret / 出力 filter)。
    """
    return ("(()=>{const w=" + "window" + ";if(w.__cap)return 'already';w.__cap=[];"
            "const S=u=>String(u).split('?')[0];"
            "const ox=w.XMLHttpRequest.prototype.open;w.XMLHttpRequest.prototype.open=function(m,u){"
            "this.__m=m;this.__u=S(u);return ox.apply(this,arguments)};"
            "const os=w.XMLHttpRequest.prototype.send;w.XMLHttpRequest.prototype.send=function(b){"
            "w.__cap.push({via:'xhr',m:this.__m,u:this.__u,keys:__ks(b)});return os.apply(this,arguments)};"
            "const of=w.fetch;w.fetch=function(u,o){o=o||{};w.__cap.push({via:'fetch',m:o.method||'GET',u:S(u&&u.url||u),keys:__ks(o.body)});"
            "return of.apply(this,arguments)};"
            "w.__ks=b=>{try{if(!b)return [];if(typeof b==='string')return b.split('&').map(p=>p.split('=')[0]).slice(0,40);"
            "if(b.forEach){const k=[];b.forEach((v,n)=>k.push(n));return k.slice(0,40)}}catch(e){}return ['?']};"
            "setTimeout(()=>{w.XMLHttpRequest.prototype.open=ox;w.XMLHttpRequest.prototype.send=os;w.fetch=of;},"
            + str(seconds * 1000) + ");return 'hooked'})()")


def js_capture_xhr_read() -> str:
    """捕捉した call を読む (URL は query を落とし、 body は **key 名だけ**)。"""
    return "(()=>{const c=window.__cap||[];return {n:c.length,calls:c.slice(-12)};})()"


# ------------------------------------------------------------------ 出力・検査
def render_md(title: str, steps: list[dict], warns: list[str] | None = None) -> str:
    """人間が 1 画面で読める step 一覧 (agent が流す前に user が目視する面)。"""
    out = [f"# driver steps: {title} ({len(steps)} steps)", ""]
    if warns:
        out += ["## ⚠️ warnings"] + [f"- {w}" for w in warns] + [""]
    out.append("## steps (js = javascript_tool、 wait = 待ち秒、 human = 人間の操作)")
    for i, s in enumerate(steps, 1):
        line = f"{i:3d}. {s['label']}"
        if s.get("wait"):
            line += f"  ⏱{s['wait']}s"
        if s.get("human"):
            line += f"  🙋 {s['human']}"
        if s.get("expect"):
            line += f"  expect={json.dumps(s['expect'], ensure_ascii=False)[:120]}"
        out.append(line)
    return "\n".join(out) + "\n"


def find_node() -> str | None:
    """node を PATH → nvm → homebrew の順に探す (launchd / RC session は PATH が痩せている)。"""
    n = shutil.which("node")
    if n:
        return n
    cands = sorted((Path.home() / ".nvm/versions/node").glob("*/bin/node"), reverse=True)
    cands += [Path("/opt/homebrew/bin/node"), Path("/usr/local/bin/node")]
    for c in cands:
        if c.exists() and os.access(c, os.X_OK):
            return str(c)
    return None


def js_syntax_check(js_list: list[str]) -> list[str]:
    """``new Function()`` で構文検査。 node が無ければ **空でなく理由を返す** (= 黙って skip しない)。"""
    node = find_node()
    if not node:
        return ["SKIP: node が見つからない (PATH / ~/.nvm / homebrew) = JS 構文は未検査"]
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as fh:
        json.dump(js_list, fh)
        path = fh.name
    src = ("const L=JSON.parse(require('fs').readFileSync(process.argv[1],'utf8'));"
           "for(const s of L){try{new Function(s)}catch(e){console.log('SYNTAX '+e.message+' :: '+s.slice(0,120))}}")
    try:
        r = subprocess.run([node, "-e", src, path], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(path)
    return [ln for ln in r.stdout.strip().splitlines() if ln]


def audit_steps(steps: list[dict], syntax: bool = True) -> list[str]:
    """step 列の site 非依存な不変条件を検査する (site 側の selftest から呼ぶ)。

    1. label があり、 js / human のどちらかを持つ
    2. server 往復 (submit / click / eval / location 代入) の step には wait がある  ← 最頻の事故
    3. 返り値に生 HTML (outerHTML / innerHTML) を混ぜていない (出力 filter 対策)
    4. async IIFE を使っていない (戻り値が {} に潰れる)
    5. 全体が JSON 化できる (steps.json に落ちる)
    6. JS が構文的に妥当 (node があれば)
    """
    probs: list[str] = []
    for i, s in enumerate(steps, 1):
        tag = f"step {i} ({s.get('label', '?')})"
        if not s.get("label"):
            probs.append(f"{tag}: label が無い")
        if not s.get("js") and not s.get("human"):
            probs.append(f"{tag}: js も human も無い (何もしない step)")
        js = s.get("js", "")
        if js:
            if any(m in js for m in ROUNDTRIP_MARKERS) and not s.get("wait"):
                probs.append(f"{tag}: server 往復なのに wait が無い (連続呼びは lockButton で捨てられる)")
            for prop in ("outerHTML", "innerHTML"):
                if prop in js:
                    probs.append(f"{tag}: 生 HTML ({prop}) を返している (出力 filter に潰される)")
            if re.search(r"\(\s*async", js):
                probs.append(f"{tag}: async IIFE は戻り値が {{}} に潰れる")
    try:
        json.dumps(steps, ensure_ascii=False)
    except (TypeError, ValueError) as e:
        probs.append(f"steps が JSON 化できない: {e}")
    if syntax:
        probs += js_syntax_check([s["js"] for s in steps if s.get("js")])
    return probs


def diff_readback(expected: dict, actual: dict, path: str = "") -> list[str]:
    """読み戻し結果と SoT の期待値を再帰的に突合 (C 層の共通部分)。 差分行の list を返す。"""
    out: list[str] = []
    for k, want in expected.items():
        p = f"{path}.{k}" if path else k
        if k not in actual:
            out.append(f"{p}: 画面に無い (期待 {want!r})")
            continue
        got = actual[k]
        if isinstance(want, dict) and isinstance(got, dict):
            out += diff_readback(want, got, p)
        elif str(want) != str(got):
            out.append(f"{p}: 期待 {want!r} ≠ 実際 {got!r}")
    return out


# ------------------------------------------------------------------ 挙動テスト (node + stub DOM)
_STUB = r"""
const rec = {clicked: [], evaled: [], changed: [], called: [], nav: null};
const mk = (name, tag, extra) => Object.assign(
  {name, tagName: tag, type: tag === 'INPUT' ? 'text' : undefined, value: '',
   dispatchEvent(e) { rec.changed.push(this.name + ':' + e.type); return true; }}, extra || {});
const elems = [mk('a.b', 'INPUT'), mk('kubun', 'SELECT', {options: [
  {value: '1', text: '基盤研究（Ｃ）'}, {value: '2', text: 'その他'}]}), mk('memo', 'TEXTAREA')];
elems.forEach(e => { elems[e.name] = e; });
const anchor = (attrs, tag) => ({
  getAttribute: k => (k in attrs ? attrs[k] : null),
  click() { rec.clicked.push(tag); }});
const anchors = [
  anchor({href: "javascript:onSave('a','1')"}, 'save'),
  anchor({onclick: "onAddRow(this,0)"}, 'add'),
  anchor({href: "javascript:onUpdate('20260908231617499','1','00061')"}, 'update')];
const doc = {
  location: {pathname: '/app/menu.do'},
  forms: [{name: 'shinsei_form'}],
  shinsei_form: {elements: elems},
  body: {innerText: '一時保存が完了しました\n 合計 21％ \n 入力できません（桁数） '},
  querySelectorAll: sel => (sel.charAt(0) === 'a' ? anchors : (sel.indexOf('input') === 0 ? elems : [])),
  getElementById: () => null};
const F = {document: doc, eval: src => { rec.evaled.push(src); },
  onInputApplication(c) { rec.called.push('onInputApplication:' + c); },
  onTransientSaveWithUpload() { rec.called.push('save'); },
  onCalculateWithUpload() { rec.called.push('calc'); },
  location: {pathname: '/app/menu.do', set href(v) { rec.nav = v; }, get href() { return rec.nav; }},
  Event: function (t) { this.type = t; }};
const F0 = {document: {location: {pathname: '/tmp.do'}, body: {innerText: ''}, forms: []}};
globalThis.window = {frames: [F0, F], document: doc,
  location: F.location, XMLHttpRequest: function () {}, fetch: function () {}};
globalThis.window.XMLHttpRequest.prototype = {open() {}, send() {}};
const R = {};
"""


def _behavior_test() -> list[str]:
    """生成した JS を stub DOM 上で実際に走らせ、 返り値と副作用を検査する。

    「構文が通る」 と「意図どおり動く」 は別 — 特に element 不在時に throw しない契約は
    実行しないと確かめられない。 node が無ければ理由を返す (黙って通さない)。
    """
    node = find_node()
    if not node:
        return ["SKIP: node が無いので挙動テスト未実施"]
    c = Ctx(frame="window.frames[1]", form="shinsei_form")
    cases = {
        "fill":        c.js_fill({"a.b": "X", "kubun": "1", "nope": "1"}, dispatch=["kubun"]),
        "select_ok":   c.js_select_by_label("kubun", "基盤研究(Ｃ)"),   # 半角括弧の SoT 表記でも当たる
        "select_ng":   c.js_select_by_label("kubun", "存在しない種目"),
        "select_miss": c.js_select_by_label("unknown", "x"),
        "click_ok":    c.js_click("onAddRow", ret="add"),
        "click_miss":  c.js_click("onNothing", ret="add"),
        "href_ok":     c.js_call_href("onSave", ret="save"),
        "href_lit":    c.js_call_href("onUpdate('20260908231617499'", ret="resume", literal=True),
        "href_miss":   c.js_call_href("onAbsent"),
        "readback":    c.js_readback(r"合計 \d+％", saved="一時保存が完了しました"),
        "nav":         c.js_nav("/app/next.do"),
        "call":        c.js_call("onInputApplication('01')", ret="01"),
        "fields":      c.js_field_dump(),
        "handlers":    c.js_handler_dump(),
        "frames":      c.js_frame_probe(),
    }
    src = _STUB + "".join("R[%s]=%s;\n" % (J(k), v) for k, v in cases.items())
    src += "R.__rec=rec;console.log(JSON.stringify(R));"
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as fh:
        fh.write(src)
        path = fh.name
    try:
        r = subprocess.run([node, path], capture_output=True, text=True, timeout=60)
    finally:
        os.unlink(path)
    if r.returncode:
        lines = r.stderr.strip().splitlines()
        err = next((ln.strip() for ln in lines if "Error" in ln and "node:" not in ln), None)
        where = next((ln.strip() for ln in lines if ".js:" in ln and "at " in ln), "")
        return ["挙動テストが落ちた: " + (err or (lines[0] if lines else "?")) + ("  @ " + where if where else "")]
    R = json.loads(r.stdout)
    rec = R["__rec"]
    want = [
        (R["fill"] == {"set": 2, "missing": ["nope"]}, "fill: 2 件 set / 不在 1 件は missing (throw しない)"),
        (rec["changed"] == ["kubun:change"], "fill: dispatch 指定の field だけ change が飛ぶ"),
        (R["select_ok"] == {"ok": "1"}, "select: 全角/半角括弧の差を吸収して当てる"),
        (R["select_ng"].get("nomatch") == "存在しない種目" and len(R["select_ng"].get("options", [])) == 2,
         "select: 不一致は nomatch + 実際の選択肢を返す (台帳を直す材料)"),
        (R["select_miss"] == {"missing": "unknown"}, "select: field 不在は missing"),
        (R["click_ok"] == "add" and "add" in rec["clicked"], "click: onclick 一致で click される"),
        (R["click_miss"] == {"missing": "onNothing"}, "click: 不在は missing (throw しない)"),
        (R["href_ok"] == "save" and any("onSave" in e for e in rec["evaled"]), "call_href: href を eval する"),
        (R["href_lit"] == "resume" and any("20260908231617499" in e for e in rec["evaled"]),
         "call_href(literal): 引数付き handler を部分一致で狙える"),
        (R["href_miss"] == {"missing": "onAbsent"}, "call_href: 不在は missing (旧実装は throw していた)"),
        (R["readback"]["saved"] is True and R["readback"]["hit"] == "合計 21％"
         and len(R["readback"]["errs"]) == 1 and R["readback"]["errs"][0].startswith("できません"),
         "readback: saved / hit / errs を同時に取る (errs はエラー語を先頭に切り出す)"),
        (rec["nav"] == "/app/next.do", "nav: location.href に代入される"),
        (R["call"] == "01" and "onInputApplication:01" in rec["called"], "call: page 関数を呼んで ret を返す"),
        (R["fields"]["n"] == 3 and "kubun:SELECT[2]" in R["fields"]["names"], "field_dump: name:TAG[選択肢数]"),
        (sorted(R["handlers"]["fns"]) == ["onAddRow", "onSave", "onUpdate"], "handler_dump: 関数名だけを重複なく"),
        (R["frames"]["n"] == 2 and R["frames"]["frames"][1]["forms"] == ["shinsei_form"]
         and R["frames"]["frames"][1]["len"] > 0, "frame_probe: frame 数 / 本文長 / form 名で main を同定できる"),
    ]
    return [msg for ok, msg in want if not ok]


# ------------------------------------------------------------------ 新サイト着手 (採取)
def probe_steps(url: str = "", frame: str = "window", form: str | None = None) -> list[dict]:
    """**新しいサイトに降りるときの採取 step 列** — 台帳 1 枚を 1 往復で埋めるための定形。

    ladder ([`machine-route-first.md#route-ladder`]) を降りて「画面しか無い」 と確定した後、
    いきなり操作を書き始めるのではなく、 まずこれを流して **frame 構造 / 画面 API / field 名 /
    内部 endpoint / 語彙** を採る。 ⑤⑥ で endpoint が見えたら段 4 (replay) へ昇格でき、
    画面 driver を書かずに済むことがある (= 降りすぎの防止)。
    """
    c = Ctx(frame=frame, form=form)
    return [
        step("① ログイン", human=f"pane で {url or '対象 URL'} を開き、 **user が** ID/PW を打つ (agent は打たない)"),
        step("② frame 構造", js=c.js_frame_probe(),
             human="frameset なら本文のある frame の index を控える → 以後 Ctx(frame='window.frames[<i>]')"),
        step("③ 画面 API", js=c.js_handler_dump(),
             human="保存 / 行追加 / 遷移らしき関数名を台帳へ。 引数付きなら literal 一致で狙う"),
        step("④ field 名", js=c.js_field_dump(),
             human="`name:TAG/type[選択肢数]` をそのまま台帳へ (値は出ない = 個人情報を持ち出さない)"),
        step("⑤ 内部 endpoint の捕捉", js=js_capture_xhr(),
             human="この後 **UI で対象操作を 1 回だけ・冪等な値で** 実行する (推測で endpoint を組まない)"),
        step("⑥ 捕捉結果", js=js_capture_xhr_read(),
             human="method / URL / body の key 名が出れば段 4 (endpoint replay) へ昇格 = 画面 driver 不要"),
        step("⑦ 語彙", js=c.js_readback("", saved=""),
             human="保存成功の文言とエラー語を実物で確認し、 readback の saved= / words= を決める"),
    ]


# ------------------------------------------------------------------ selftest
def _selftest() -> int:
    bad = 0

    def chk(cond, msg):
        nonlocal bad
        print(("✓ " if cond else "✗ ") + msg)
        if not cond:
            bad += 1

    frameset = Ctx(frame="window.frames[1]", form="shinsei_form")
    plain = Ctx()

    # 1. frameset 版の JS 形 (2026-09-08 に実機で通った形と同一)
    js = frameset.js_fill({"a.b": "x"}, dispatch=["a.b"])
    chk(js.startswith("(()=>{const f=window.frames[1];const fm=f.document.shinsei_form;const V="), "frameset fill の prologue")
    chk("missing.push(n)" in js and "return {set:set.length,missing};" in js, "fill は missing を返し throw しない")
    chk("\\u" in frameset.js_fill({"a": "日本語"}), "非 ASCII は \\uXXXX に逃げる")

    # 2. form 無し (SPA / 素の form) は name/id 検索に切り替わる
    chk("querySelector" in plain.js_fill({"a": "x"}) and "fm.elements" not in plain.js_fill({"a": "x"}), "form 無しは name/id 検索")

    # 3. missing を throw しない: 見つからない系 helper は全部 {missing} を返す
    for name, js in (("call_href", frameset.js_call_href("onSave")), ("click", frameset.js_click("onAdd")),
                     ("select", frameset.js_select_by_label("n", "l"))):
        chk("missing" in js, f"{name} は missing を返す")

    # 3b. literal 一致 = 引数付き handler (正規表現メタ文字を含む) を狙う経路
    lit = frameset.js_call_href("onUpdate('2026090823161'", ret="resume", literal=True)
    chk(".includes(" in lit and "new RegExp" not in lit, "call_href(literal) は includes で照合")
    chk("h.includes(" in frameset.js_click("onEdit('r7'", literal=True), "click(literal) は includes で照合")

    # 4. readback は保存文言・hit・エラー語を 1 回で取る
    rb = frameset.js_readback("合計 \\d+", saved="保存が完了しました")
    chk(all(k in rb for k in ("saved:", "hit:", "errs:")), "readback は saved/hit/errs を同時に返す")
    chk("メッセージが出た" in rb, "既定の除外語が入る")

    # 5. audit: 往復に wait が無ければ検出、 付いていれば通る
    probs = audit_steps([step("保存", js=frameset.js_call_href("onSave"))], syntax=False)
    chk(any("wait" in p for p in probs), "wait 欠落を検出する")
    chk(not audit_steps([step("保存", js=frameset.js_call_href("onSave"), wait=4)], syntax=False), "wait があれば通る")
    chk(any("outerHTML" in p for p in audit_steps([step("x", js="(()=>document.body.outerHTML)()", wait=1)], syntax=False)), "生 HTML 返しを検出")
    chk(any("async" in p for p in audit_steps([step("x", js="(async()=>1)()")], syntax=False)), "async IIFE を検出")

    # 6. JS 構文検査が実際に走る (node が見つからないなら理由を返す = 黙って通さない)
    allj = [frameset.js_fill({"a": "1"}), frameset.js_select_by_label("n", "l"), frameset.js_readback("x", saved="y"),
            frameset.js_nav("/a.do"), frameset.js_call("f('1')"), frameset.js_call_href("onSave"), frameset.js_click("onAdd"),
            frameset.js_text(), frameset.js_field_dump(), frameset.js_handler_dump(), frameset.js_frame_probe(),
            plain.js_fill({"a": "1"}),
            plain.js_select_by_label("n", "l"), plain.js_field_dump(), js_capture_xhr(), js_capture_xhr_read(),
            frameset.js_call_href("onUpdate('X','1','00061'", ret="resume", literal=True),
            frameset.js_click("onEdit('r7',2", ret="edit", literal=True),
            plain.js_call_href("onSave"), plain.js_click("onAdd"), plain.js_readback("x", saved="y")]
    res = js_syntax_check(allj)
    chk(not res, f"生成した {len(allj)} 本の JS が構文的に妥当" + (f" — {res}" if res else ""))
    chk(find_node() is not None, "node を発見 (PATH / nvm / homebrew)")

    # 7. probe は値を返さない (個人情報 + 出力 filter)
    chk(".value" not in frameset.js_field_dump(), "field_dump は値を返さない")
    chk("getAttribute('href')" in frameset.js_handler_dump() or "href" in frameset.js_handler_dump(), "handler_dump は href を読む")
    chk("fns:" in frameset.js_handler_dump() and "hrefs" not in frameset.js_handler_dump(), "handler_dump は関数名だけ返す")
    chk("split('?')[0]" in js_capture_xhr(), "capture は query string を落とす")

    # 8. diff_readback
    d = diff_readback({"total": 700, "y": {"2027": 300}}, {"total": "700", "y": {"2027": 400}})
    chk(d == ["y.2027: 期待 300 ≠ 実際 400"], f"diff_readback (数値は文字列比較で吸収): {d}")
    chk(diff_readback({"a": 1}, {}) == ["a: 画面に無い (期待 1)"], "欠落を報告")

    # 9. render_md
    md = render_md("t", [step("a", js="1", wait=2), step("b", human="人間")])
    chk("⏱2s" in md and "🙋 人間" in md, "render_md")

    # 9b. 採取 step 列そのものが不変条件を満たす
    pst = probe_steps("https://example.invalid/app", frame="window.frames[1]", form="f")
    chk(len(pst) == 7 and all(x.get("human") for x in pst), "probe_steps: 7 段すべてに人間向けの指示がある")
    chk(not audit_steps(pst), "probe_steps: audit を通る")

    # 10. 生成した JS を stub DOM 上で実際に走らせる (構文が通る ≠ 意図どおり動く)
    fails = _behavior_test()
    for msg in fails:
        chk(False, "挙動: " + msg)
    chk(not fails, f"挙動テスト (node + stub DOM): {'全項目 pass' if not fails else str(len(fails)) + ' 件 fail'}")

    print("selftest", "OK" if not bad else f"FAIL ({bad})")
    return 1 if bad else 0


def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description="site 非依存の web driver harness")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--probe", action="store_true", help="新サイト採取の step 列を出す")
    ap.add_argument("--url", default="", help="--probe: 対象 URL (表示用)")
    ap.add_argument("--frame", default="window", help="--probe: 対象 window の JS 式")
    ap.add_argument("--form", default=None, help="--probe: document.<form> の name (無ければ name/id 検索)")
    ap.add_argument("--out", help="--probe: steps.json の出力先")
    a = ap.parse_args()
    if a.selftest:
        return _selftest()
    if a.probe:
        steps = probe_steps(a.url, a.frame, a.form)
        probs = audit_steps(steps)
        if a.out:
            Path(a.out).write_text(json.dumps({"probe": a.url, "steps": steps}, ensure_ascii=False, indent=1), encoding="utf-8")
        print(render_md("probe " + (a.url or "(新サイト)"), steps, probs or None))
        print("→ ② の結果で frame を決め、 ③④ を台帳に写し、 ⑤⑥ が実れば段 4 へ。")
        print("   規約 = claude-config/conventions/web-form-automation.md#step-driver-harness")
        return 1 if probs else 0
    print(__doc__.split("\n\n")[0])
    return 0


if __name__ == "__main__":
    sys.exit(_main())
