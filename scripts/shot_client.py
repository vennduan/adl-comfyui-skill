# -*- coding: utf-8 -*-
"""历史短剧视频生成 · 命令行客户端

    python shot_client.py --url $URL --token $TOKEN health
    python shot_client.py --url $URL --token $TOKEN example
    python shot_client.py --url $URL --token $TOKEN submit --script shot.json
    python shot_client.py --url $URL --token $TOKEN wait    --job 8a95fb071e1d
    python shot_client.py --url $URL --token $TOKEN fetch   --job 8a95fb071e1d --dir ./产物
    python shot_client.py --url $URL --token $TOKEN run --script shot.json --download ./产物

`run` = submit + wait + 打印产物, 这是最常用的一条; 加 --download 会顺手把文件拉下来。
`fetch` 可以事后按 job_id 把产物补下来。

任务里带上 shot_id(如 "E01_S03"), 产物就有可预测的名字, 否则是
分镜视频_00020_.mp4 这种对不上剧本的自动编号。

URL / TOKEN 也可以写环境变量 ADL_URL / ADL_TOKEN, 免得每次敲。
只依赖标准库, 拷到哪都能跑。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def call(url, token, path, body=None, timeout=60):
    req = urllib.request.Request(
        url.rstrip("/") + path,
        data=json.dumps(body, ensure_ascii=False).encode() if body is not None else None,
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body)
        except ValueError:
            return e.code, {"error": body[:400]}
    except urllib.error.URLError as e:
        # 404 和连不上在这里面, 分开说 —— AutoDL 端口对不上就是 404, 很容易误判
        return 0, {"error": f"连不上 {url}: {e.reason}"}


def show_401_404(url, st, r):
    if st == 401:
        print("401 —— token 错了或没带对。核对 Authorization: Bearer <token>。", file=sys.stderr)
    elif st == 404:
        print("404 —— 地址或端口不对。AutoDL 只把 6006/6008 映射到公网，"
              "服务跑在别的端口上时公网地址一律 404（不是服务没起）。", file=sys.stderr)
    elif st == 0:
        print(f"网络不通：{r.get('error')}", file=sys.stderr)
    else:
        print(json.dumps(r, ensure_ascii=False, indent=1), file=sys.stderr)


def wait_job(url, token, job, interval=45, quiet=False):
    """轮询到 done/failed。中途 Ctrl-C 不会丢任务 —— 状态在服务器上落着。"""
    t0 = time.time()
    while True:
        st, r = call(url, token, f"/task/{job}", timeout=60)
        if st != 200:
            show_401_404(url, st, r)
            return None
        s = r.get("status")
        if not quiet:
            print(f"[{int(time.time()-t0):5d}s] {s}"
                  f"  已用 {r.get('elapsed', int(time.time()-t0))}s"
                  f"{'  ' + r['error'] if r.get('error') else ''}", flush=True)
        if s in ("done", "failed"):
            return r
        if s == "queued":
            print(f"        前面还有 {r.get('queue_depth', '?')} 个任务", flush=True)
        time.sleep(interval)


def download(url, token, paths, dest_dir, quiet=False):
    """按 *_download 路径把产物拉到本地。返回本地路径列表。

    path 就是 result 里的 *_download 字段(已百分号编码), 别自己拼 —— 产物名里有中文,
    HTTP 请求行按 latin-1 解码, 不编码会变乱码找不到文件。
    """
    import urllib.parse as _u
    os.makedirs(dest_dir, exist_ok=True)
    base = url.rstrip("/")
    root = _u.urlsplit(base)
    got = []
    for p in paths:
        rel = p if isinstance(p, str) else p.get("download") or ""
        if not rel:
            continue
        url_path = _u.urljoin(base, rel)
        req = urllib.request.Request(url_path, headers={"Authorization": "Bearer " + token})
        try:
            with urllib.request.urlopen(req, timeout=300) as r:
                data = r.read()
                cd = r.headers.get("Content-Disposition", "")
        except urllib.error.HTTPError as e:
            print(f"下载失败 {p}: HTTP {e.code}", file=sys.stderr)
            continue
        name = _u.unquote(os.path.basename(_u.urlsplit(url_path).path))
        if "filename*=UTF-8''" in cd:                 # 服务端给的名字更可靠
            name = _u.unquote(cd.split("filename*=UTF-8''", 1)[1].split(";")[0])
        dst = os.path.join(dest_dir, os.path.basename(name))
        with open(dst, "wb") as f:
            f.write(data)
        got.append(dst)
        if not quiet:
            print(f"  下载 {len(data)/1048576:.1f} MB -> {dst}")
    return got


def _result_paths(result):
    """把 result 里的 *_download 路径和 files 清单凑成一份可下载列表。

    files 清单和顶层的 video / characters 是同一批东西, 两边都收才能兼容老格式,
    所以必须去重 —— 不去重会把每个文件下两遍, 一支 20 MB 的 mp4 就是白跑一趟。
    """
    seen, items = set(), []
    def add(url):
        if url and url not in seen:
            seen.add(url)
            items.append({"download": url})
    for f in result.get("files") or []:
        add(f.get("download") or f.get("path") or
            ("/file/" + _q(f["file"]) if f.get("file") else None))
    if result.get("video"):
        add(result.get("video_download") or "/file/" + _q(result["video"]))
    for ch in result.get("characters") or []:
        if ch.get("portrait"):
            add(ch.get("portrait_download") or "/file/" + _q(ch["portrait"]))
    if result.get("voiceover"):
        add("/file/" + _q(result["voiceover"]))
    return items


def _q(name):
    import urllib.parse as _u
    return _u.quote(name)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default=os.environ.get("ADL_URL", ""))
    ap.add_argument("--token", default=os.environ.get("ADL_TOKEN", ""))
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("health", help="探活")
    sub.add_parser("example", help="拿一份可直接提交的模板")

    p = sub.add_parser("submit", help="提交一个任务, 立刻返回 job_id")
    p.add_argument("--script", required=True, help="任务 JSON 文件")

    p = sub.add_parser("wait", help="轮询一个已提交的任务")
    p.add_argument("--job", required=True)
    p.add_argument("--interval", type=int, default=45)

    p = sub.add_parser("run", help="提交 + 轮询到底, 最常用")
    p.add_argument("--script", required=True)
    p.add_argument("--interval", type=int, default=45)
    p.add_argument("--out", default="", help="把产物信息写到这个文件(可选)")
    p.add_argument("--download", default="", metavar="目录",
                   help="完成后把产物(视频/定妆照/旁白)下载到这个目录")

    p = sub.add_parser("fetch", help="按 job_id 把产物下载到本地")
    p.add_argument("--job", required=True)
    p.add_argument("--dir", required=True, help="下载到哪个目录")

    a = ap.parse_args()
    if not a.url or not a.token:
        print("要给 --url 和 --token（或设 ADL_URL / ADL_TOKEN）", file=sys.stderr)
        return 2

    if a.cmd == "health":
        st, r = call(a.url, a.token, "/health")
        print(json.dumps(r, ensure_ascii=False, indent=1))
        if st in (401, 404, 0):
            print(file=sys.stderr)
            show_401_404(a.url, st, r)
            return 1
        return 0 if r.get("ok") else 1

    if a.cmd == "example":
        st, r = call(a.url, a.token, "/example")
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if st == 200 else 1

    if a.cmd in ("submit", "run"):
        try:
            with open(a.script, encoding="utf-8") as f:
                task = json.load(f)
        except Exception as e:
            print(f"读不了 {a.script}: {e}", file=sys.stderr)
            return 2
        st, r = call(a.url, a.token, "/task", body=task)
        if st not in (200, 202):
            show_401_404(a.url, st, r)
            return 1
        job = r["job_id"]
        print(f"已提交 job_id={job}  队列位置 {r.get('queue_depth')}", flush=True)
        if a.cmd == "submit":
            return 0
        res = wait_job(a.url, a.token, job, a.interval)
        if res is None:
            return 1
        if res["status"] == "failed":
            print(f"失败：{res.get('error')}", file=sys.stderr)
            return 1
        out = res.get("result") or {}
        print("\n完成，耗时 %.0f 秒" % res.get("elapsed", 0))
        for ch in out.get("characters") or []:
            print(f"  定妆照  {ch['name']}: {ch['portrait']}")
        print(f"  视频    {out.get('video')}")
        if out.get("voiceover"):
            print(f"  旁白    {out['voiceover']}")
        if a.download:
            got = download(a.url, a.token, _result_paths(out), a.download)
            if not got:
                print("没有下载到任何文件", file=sys.stderr)
        if a.out:
            # 任务已经成功了, 写文件失败不能把结果弄丢 —— 建目录, 失败只警告。
            try:
                d = os.path.dirname(os.path.abspath(a.out))
                if d:
                    os.makedirs(d, exist_ok=True)
                with open(a.out, "w", encoding="utf-8") as f:
                    json.dump(res, f, ensure_ascii=False, indent=1)
                print(f"\n完整结果已写入 {a.out}")
            except OSError as e:
                print(f"\n（写 {a.out} 失败: {e} —— 但上面的产物是好的，别重跑）", file=sys.stderr)
        return 0

    if a.cmd == "fetch":
        st, r = call(a.url, a.token, f"/task/{a.job}")
        if st != 200 or r.get("status") != "done":
            show_401_404(a.url, st, r)
            print(f"任务还没完成: {r.get('status')}", file=sys.stderr)
            return 1
        got = download(a.url, a.token, _result_paths(r.get("result") or {}), a.dir)
        return 0 if got else 1

    if a.cmd == "wait":
        res = wait_job(a.url, a.token, a.job, a.interval)
        if res is None:
            return 1
        print(json.dumps(res, ensure_ascii=False, indent=1))
        return 0 if res["status"] == "done" else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
