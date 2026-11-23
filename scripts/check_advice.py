"""Check the cached AI advice of the login-mode jobs against their writing guides (the acceptance check of PR "面試回饋改版").

Prints, per account, the stable features of every group and the full text of every CURRENT advice (its basis matches the present
stable lists and prompt version; older advice is hidden in the UI too), then checks ALL fields (summary, do, why, test, avoid):
features / keywords / media / time slots that are not on the stable lists, numbers that match no stable value, inferential or
causal wording, and the direction of every `do` (heuristic: confirm flagged ones by eye).

Usage (read-only; run from the repo root):
  python scripts/check_advice.py > reports/advice_acceptance_raw.md
Credentials, either:
  CHECK_EMAIL=... CHECK_PASSWORD=... python scripts/check_advice.py   # reads as that user through RLS (anon key from .env.local)
  python scripts/check_advice.py                                      # no variables: service key from .env, as the pipeline does
The password is only read from the environment; nothing is written anywhere.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import httpx  # noqa: E402

from src.pipeline.db import Db  # noqa: E402


def rls_db() -> Db:
    env = {}
    for name in (".env", ".env.local"):
        f = ROOT / name
        if f.exists():
            env.update(dict(l.strip().split("=", 1) for l in f.read_text().splitlines() if "=" in l and not l.lstrip().startswith("#")))
    url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or env["NEXT_PUBLIC_SUPABASE_URL"]
    anon = os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY") or env["NEXT_PUBLIC_SUPABASE_ANON_KEY"]
    r = httpx.post(f"{url}/auth/v1/token?grant_type=password", headers={"apikey": anon}, timeout=30,
                   json={"email": os.environ["CHECK_EMAIL"], "password": os.environ["CHECK_PASSWORD"]})
    r.raise_for_status()
    return Db(url, anon, bearer=r.json()["access_token"])

import json, math, re  # noqa: E402

from src.pipeline.advice import advice_basis  # noqa: E402

GOAL_GROUP = {"提高按讚、建立好感": "共鳴型", "帶動討論": "討論型"}
GOAL_METRIC = {"共鳴型": "按讚率", "討論型": "回覆率"}  # groups are defined by like / reply percentiles
hu = lambda x: math.floor(x + 0.5)  # JS Math.round
fmt = lambda f, v: f"{hu(v*100)}%" if f["is_share"] else f"{hu(v)} 字"
FORBID = re.compile(r"顯著|明顯優於|統計上|p\s*值|p\s*=|證明")
SOFT = re.compile(r"(?:來|藉此|進而)(?:嘗試)?(?:提升|提高|增加|帶動)|顯示|導致|造成|因為|因此|確保|保證|必然|一定|以提升|為提升|有助於|提升互動|相關(?!連結|活動|資訊|頁面|商品)")
# topics a text can talk about -> regex. The four listed features first, then topics that can NEVER be on the stable list.
TOPICS = {
    "char_median": r"字數|字以內|字以上|字以下|字左右|\d+\s*字|篇幅|長度|長文|短文|簡短|精簡",
    "question_share": r"提問|問句|疑問|詢問|發問|問題|？|\?",
    "link_share": r"連結|網址|外部網站|URL",
    "evening_share": r"晚間|晚上|夜間|傍晚|18\s*點?\s*[–\-~至到]\s*23|18\s*點|23\s*點|時段|發文時間|發布時間|發佈時間",
    "(關鍵字)": r"關鍵字|關鍵詞|常見詞|主題詞",
    "(貼文類型／hashtag／mention)": r"貼文類型|hashtag|Hashtag|標籤|mention|提及帳號|@\w+",
    "(圖片／影片／素材)": r"圖片|影片|照片|輪播|貼圖|素材|短影音|圖文",
    "(其他時段／星期)": r"上午|下午|凌晨|週[一二三四五六日]|星期|平日|週末|假日",
}
LABEL = {"char_median": "字數", "question_share": "提問句", "link_share": "含連結", "evening_share": "晚間"}
FIELD_TXT = {"summary": "summary", "do": "do", "why": "why", "test": "test", "avoid": "avoid"}
INCR, DECR = r"增加|提高|提升|擴充|拉長|加長|加入|多用|補上|附上|放入|放置|安排|使用", r"減少|縮短|控制在|精簡|避免|移除|不放|不置入|不包含|避開|低於"

db = rls_db() if os.environ.get("CHECK_EMAIL") else Db()
jobs = {j["id"]: j for j in db.select("jobs", {"select": "id,username,mode,status", "mode": "eq.login"})}
out, flags, info = [], [], []
n_checked = 0
for jid, j in sorted(jobs.items(), key=lambda kv: kv[1]["username"]):
    s = db.select("job_summaries", {"job_id": f"eq.{jid}", "select": "group_analysis,llm_advice"})[0]
    ga = s["group_analysis"]["real"]; wg = ga["writing_guide"]
    out.append(f"\n## @{j['username']}（真實貼文 {wg['n_posts']} 篇；前後各 {wg['halves']}；分組 {ga['counts']}）")
    for g in ("共鳴型", "討論型", "低迷型"):
        fs = wg["groups"][g]["stable_features"]
        out.append(f"- **{g}**（{wg['groups'][g]['goal']}）穩定特徵 {len(fs)} 項" + ("：無" if not fs else ""))
        for f in fs:
            d = "較高" if f["direction"] == "higher" else "較低"
            out.append(f"  - {f['label']}：{g}{d}（{g} {fmt(f, f['group_value'])}，其他 {fmt(f, f['others_value'])}；{g} {f['n_group']} 篇、其他 {f['n_others']} 篇）")
    try: store = json.loads(s["llm_advice"])
    except Exception: store = {"entries": {}}
    for key, e in sorted(store.get("entries", {}).items()):
        if e.get("goal") not in GOAL_GROUP:
            continue  # a goal that no longer exists (renamed in v7): the UI ignores it too
        goal, grp = e["goal"], GOAL_GROUP[e["goal"]]
        if e.get("basis") != advice_basis(goal, s):
            continue  # written for an older guide: the UI hides it too
        n_checked += 1
        a = e["advice"]; tag = f"@{j['username']} / {goal} / {e['model']}"
        tgt = wg["groups"][grp]["stable_features"]; low = wg["groups"]["低迷型"]["stable_features"]
        cands = [(grp, f) for f in tgt] + [("低迷型", f) for f in low]
        allowed = {f["key"] for _, f in cands}
        rep = (ga["groups"].get(grp) or {}).get("profile_of_representatives") or {}
        repkw = [k["word"] for k in (rep.get("keywords") or [])[:5]]
        out.append(f"\n### {tag}（{e['generated_at']}）\n**summary**：{a['summary']}")
        fields = [("summary", a["summary"])] + [(f"action {i} {n}", ac[n]) for i, ac in enumerate(a["actions"], 1) for n in ("do", "why", "test")] + [("avoid", a["avoid"])]
        for i, ac in enumerate(a["actions"], 1):
            out.append(f"{i}. **做法**：{ac['do']}\n   - 依據：{ac['why']}\n   - 驗證：{ac['test']}")
        out.append(f"**避開**：{a['avoid']}")
        whole = " ".join(t for _, t in fields)
        if FORBID.search(whole): flags.append((tag, "全文", "推論用語（硬性）", FORBID.search(whole).group(0)))
        sw = sorted(set(SOFT.findall(whole)))
        if sw: flags.append((tag, "全文", "因果／關聯語氣（軟性）", "、".join(sw)))
        for name, txt in fields:
            # 1) features / topics outside the stable list (includes keywords, types, media, other time slots)
            for topic, rx in TOPICS.items():
                if re.search(rx, txt) and topic not in allowed:
                    flags.append((tag, name, "提到不在穩定清單內的特徵", f"{LABEL.get(topic, topic)}：{re.search(rx, txt).group(0)}"))
            for kw in repkw:  # the representative posts' common keywords handed to the model as background only
                if kw and kw in txt: flags.append((tag, name, "提到代表貼文的關鍵字（不在穩定清單）", kw))
            # 2) numbers must belong to a cited stable feature (why/avoid) -- numbers in do/summary/test are matched against all stable values
            ok = {str(wg["n_posts"]), *map(str, wg["halves"]), "18", "23"}  # 18 and 23 come from the label 晚間（18–23 點）
            for _, f in cands: ok |= {str(f["n_group"]), str(f["n_others"]), re.sub(r"\D", "", fmt(f, f["group_value"])), re.sub(r"\D", "", fmt(f, f["others_value"]))}
            if name in ("summary", "avoid") or name.endswith(" why") or name.endswith(" do"):
                text_nums = re.sub(r"18\s*點?\s*[–\-~至到]\s*23\s*點?(\s*59\s*分)?", "", txt)
                # an approximate range (約 30 字左右 for a median of 26) is allowed: within 20 % of a stable value
                vals = [float(x) for x in ok if x.isdigit()]
                stray = {x for x in set(re.findall(r"\d+", text_nums)) - ok if not any(v and abs(float(x) - v) <= 0.2 * v for v in vals)}
                if stray: flags.append((tag, name, "數字不在穩定清單內（可能自創門檻）", "、".join(sorted(stray))))
        # 3) why / avoid: must name a stable feature, with its group, and the numbers must match it
        def cite(name, txt, pool):
            named = [x for x in ("共鳴型", "討論型", "低迷型") if x in txt]
            hit = [(g, f) for g, f in pool if re.search(TOPICS[f["key"]], txt) and (not named or g in named)]
            if not hit: flags.append((tag, name, "沒有引用穩定清單內的特徵", txt[:50])); return
            for g, f in hit:
                miss = {str(f["n_group"]), str(f["n_others"])} - set(re.findall(r"\d+", txt))
                if miss: flags.append((tag, name, "格式不完整：沒有寫出篇數（prompt 規則 1）", f"{g}・{f['label']} 缺 {sorted(miss)}"))
                wrong = []
                for want in (re.sub(r"\D", "", fmt(f, f["group_value"])), re.sub(r"\D", "", fmt(f, f["others_value"]))):
                    if want not in set(re.findall(r"\d+", txt)): wrong.append(want)
                if wrong: flags.append((tag, name, "格式不完整：沒有寫出數值（prompt 規則 1）", f"{g}・{f['label']} 缺 {wrong}（正確：{g} {fmt(f,f['group_value'])}／其他 {fmt(f,f['others_value'])}）"))
        for i, ac in enumerate(a["actions"], 1): cite(f"action {i} why", ac["why"], cands)
        if not low:
            if "沒有" not in a["avoid"]: flags.append((tag, "avoid", "低迷型無穩定特徵，但沒有說明沒有依據", a["avoid"][:50]))
        else:
            cite("avoid", a["avoid"], [("低迷型", f) for f in low])
        # 4) a do must rest on exactly one feature (rule 2) and must not push against the direction of its feature (heuristic -> confirm by eye)
        for i, ac in enumerate(a["actions"], 1):
            dtopics = [t for t, rx in TOPICS.items() if re.search(rx, ac["do"]) and t in LABEL]
            if len(dtopics) > 1: info.append((tag, f"action {i} do", f"同時談到多個特徵：{[LABEL[t] for t in dtopics]}"))
            for f in tgt:
                if f["key"] in dtopics and len(dtopics) == 1:
                    neg = re.search(r"不要|不放|不加|不用|不寫|別|避免|省略", ac["do"])
                    up = not neg and re.search(INCR, ac["do"]) and not re.search(DECR, ac["do"]); down = neg or (re.search(DECR, ac["do"]) and not re.search(INCR, ac["do"]))
                    names_value = re.sub(r"\D", "", fmt(f, f["group_value"])) in re.findall(r"\d+", ac["do"])
                    if not names_value and ((f["direction"] == "lower" and up) or (f["direction"] == "higher" and down)):
                        flags.append((tag, f"action {i} do", "做法的方向疑似和特徵相反（請人工確認）", f"{f['label']}：{grp}{'較低' if f['direction']=='lower' else '較高'}；do={ac['do'][:40]}"))
        # 5) v7 rules (each is also enforced by the server-side validator; listed here so old advice is caught too)
        n_target = len(tgt)
        if len(a["actions"]) != n_target:
            flags.append((tag, "actions", "點數和目標組穩定特徵數不同", f"{len(a['actions'])} 點，目標組穩定特徵 {n_target} 個"))
        seen = {}
        for i, ac in enumerate(a["actions"], 1):
            # which target feature this action is about: the one its why cites (fall back to the do)
            cited = [f["key"] for f in tgt if re.search(TOPICS[f["key"]], ac["why"]) and (grp in ac["why"] or "低迷型" not in ac["why"])]
            if not cited:
                cited = [f["key"] for f in tgt if re.search(TOPICS[f["key"]], ac["do"])]
            for key in cited[:1]:
                if key in seen:
                    flags.append((tag, f"action {i}", "與前面的點重複同一個特徵", f"{LABEL[key]}（同 action {seen[key]}）"))
                seen.setdefault(key, i)
            target_keys = {f["key"] for f in tgt}
            low_only = [f for f in low if f["key"] not in target_keys and re.search(TOPICS[f["key"]], ac["do"])]
            if "低迷型" in ac["do"] or "低迷型" in ac["why"] or low_only:
                flags.append((tag, f"action {i} do", "do 引用了低迷型特徵（低迷型只能用在 avoid）", ac["do"][:50]))
            if re.search(r"(調整|提高|降低|增加|減少|拉高|拉低).{0,8}(比例|占比)|(比例|占比).{0,4}(調整|提高|降低|拉到|增加|減少)|(減少|降低|增加|提高|多用|少用|多放|少放|多加|少加).{0,6}(提問|問句|連結|網址|晚間)", ac["do"]):
                flags.append((tag, f"action {i} do", "把占比寫成「調整比例」（應寫這篇要不要）", ac["do"][:50]))
            if re.search(r"\d+\s*[%％]", ac["do"]):
                flags.append((tag, f"action {i} do", "把占比寫成百分比目標（應寫這篇要不要）", ac["do"][:50]))
            for m in re.finditer(r"(約|大約)?\s*(\d+)\s*字(左右|以內|以下|以上|上下|內)?", ac["do"]):
                if not m.group(1) and not m.group(3):
                    flags.append((tag, f"action {i} do", "字數寫成單篇精確目標（應寫大約範圍）", m.group(0)))
            # numbers in a do must come from the target group's own values, never the "others" side or 低迷型
            own = {re.sub(r"\D", "", fmt(f, f["group_value"])) for f in tgt}
            foreign = {re.sub(r"\D", "", fmt(f, f["others_value"])) for f in tgt} | {re.sub(r"\D", "", fmt(f, v)) for f in low for v in (f["group_value"], f["others_value"])}
            bad = [x for x in re.findall(r"\d+", re.sub(r"18\s*點?\s*[–\-~至到]\s*23\s*點?", "", ac["do"])) if x in foreign and x not in own]
            if bad:
                flags.append((tag, f"action {i} do", "do 用了「其他貼文」或低迷型的數值當目標", "、".join(bad)))
            if re.search(r"23\s*點\s*(?:以後|後)|午夜|凌晨", ac["do"]):
                flags.append((tag, f"action {i} do", "時段寫法不符定義（晚間 18:00–23:59，非晚間寫 18 點以前）", ac["do"][:50]))
            metric = GOAL_METRIC[grp]; other = "回覆率" if metric == "按讚率" else "按讚率"
            if metric not in ac["test"] or other in ac["test"] or re.search(r"觸及|觀看|互動率|曝光", ac["test"]):
                flags.append((tag, f"action {i} test", f"驗證指標與組別不符（{grp}應比{metric}中位數）", ac["test"][:50]))
        # rounding direction of a length range (must not be stricter than the group's own median) and the avoid direction
        for f in tgt:
            if f["key"] != "char_median":
                continue
            v = hu(f["group_value"])
            for i, ac in enumerate(a["actions"], 1):
                for m in re.finditer(r"(\d+)\s*字", ac["do"]):
                    x = int(m.group(1))
                    if (f["direction"] == "lower" and x < v) or (f["direction"] == "higher" and x > v):
                        flags.append((tag, f"action {i} do", "字數範圍比目標組中位數更嚴（取整方向錯）", f"{m.group(0)}；{grp}中位數 {v} 字，{'較低→往上取' if f['direction']=='lower' else '較高→往下取'}"))
        av = a["avoid"].split("（低迷型")[0]
        if re.search(r"不要|別再|勿", av):
            flags.append((tag, "avoid", "寫成「不要…」命令句（應寫要避開的寫法本身）", av[:50]))
        WORD = {"question_share": "提問|問句", "link_share": "連結|網址", "evening_share": "晚間", "char_median": "字"}
        for f in low:
            w = WORD[f["key"]]
            if not re.search(w, av):
                continue
            if f["key"] == "char_median":
                bad_dir = (f["direction"] == "higher" and not re.search(r"以上|超過|過長|長文|長篇", av)) or (f["direction"] == "lower" and not re.search(r"以下|以內|過短|短文|短篇", av))
            else:
                neg = bool(re.search(rf"(沒有|不含|缺少|無|少了|不帶|不放|沒放|沒加|不在)[^，。；]{{0,4}}({w})", av))
                bad_dir = (f["direction"] == "lower" and not neg) or (f["direction"] == "higher" and neg)
            if bad_dir:
                flags.append((tag, "avoid", "方向和低迷型特徵相反", f"{f['label']}：低迷型{'較低' if f['direction']=='lower' else '較高'}；avoid={av[:40]}"))
        if "觸及" in whole:
            flags.append((tag, "全文", "使用了「觸及」（沒有觸及資料）", ""))
        for nm, t in (("summary", a["summary"]), ("avoid", a["avoid"].split("（低迷型")[0])):
            if re.search(r"(調整|提高|降低|增加|減少|拉高|拉低).{0,8}(比例|占比)|(比例|占比).{0,4}(調整|提高|降低|拉到|增加|減少)|(減少|降低|增加|提高|多用|少用|多放|少放|多加|少加).{0,6}(提問|問句|連結|網址|晚間)", t):
                flags.append((tag, nm, "把占比寫成「調整比例」（應寫這篇要不要）", t[:50]))
            for m in re.finditer(r"(約|大約)?\s*(\d+)\s*字(左右|以內|以下|以上|上下|內)?", t):
                if not m.group(1) and not m.group(3):
                    flags.append((tag, nm, "字數寫成精確門檻（應寫大約範圍）", m.group(0)))
        if re.search(r"\d+\s*[%％]", a["summary"]):
            flags.append((tag, "summary", "把占比寫成百分比目標", a["summary"][:50]))
print("\n".join(out))
print(f"\n\n# 檢查範圍：{n_checked} 份建議（只含目前穩定清單下產生的；舊清單下的建議不算）")
print("\n## 腳本檢查結果（違規 / 疑似）", len(flags))
for t in flags: print("-", *t)
print("\n## 補充（每個 do 是否只依據一個特徵，僅供參考）", len(info))
for t in info: print("-", *t)
