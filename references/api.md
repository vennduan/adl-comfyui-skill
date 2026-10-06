# API 契约

服务是**异步**的：一镜要跑十几到二十多分钟，同步接口会被网关掐断、进程重启任务就丢。
所以提交立刻返回 `job_id`，之后轮询。

- 基础地址：`https://<域名>:<端口>`（AutoDL 只把 6006/6008 映射到公网）
- 所有接口都要鉴权，见下
- 全部返回 JSON，`Content-Type: application/json; charset=utf-8`

---

## 鉴权

每次请求都要带 token，三种带法任选：

```bash
-H "Authorization: Bearer <token>"     # 推荐
-H "X-Shot-Token: <token>"             # 等价
"https://.../health?token=<token>"     # 浏览器方便，但 token 会进访问日志
```

没有或不对一律 **401**，body：

```json
{"error": "缺 token 或 token 不对", "how": "加头 Authorization: Bearer <token> 或 X-Shot-Token: <token>"}
```

token 在服务器的 `shot_token.txt`（权限 600），启动日志第一行也会打一遍。
比较用 `compare_digest`，不区分大小写地只对 `bearer ` 前缀做识别。

---

## `GET /health`

探活，顺带确认 ComfyUI 通不通、队列里排了几个。

```json
{"ok": true, "comfy": "http://127.0.0.1:8188", "queued": 0}
```

- `200` + `ok:true` → 服务和 ComfyUI 都正常
- `200` + `ok:false` → 服务活着但连不上 ComfyUI，看 `error`
- `503` → 同上，服务侧已经探到了
- `401` → token 问题

---

## `GET /example`

返回一份**可以直接提交**的请求模板。

```jsonc
{
  "shot": { "prompt": "...", "seconds": 5, "voice": "api_elevenlabs_...mp3", "steps": 20, "turbo": false },
  "characters": [ { "name": "智伯", "positive": "...", "seed": 42 }, ... ],
  "_note": "voice 已换成 input/ 里实际存在的 xxx; 可选: a.mp3, b.wav, ..."   // 仅当模板里的默认文件不存在时出现
}
```

`voice` 已经换成了 `input/` 里**实际存在**的文件 —— 换机器部署后默认名往往不存在，
不换的话调用方拿到的模板会被自己的校验挡下来。`_note` 列出可选声线。

---

## `POST /task`

**入参**

| 字段 | 类型 | 边界 | 说明 |
|---|---|---|---|
| `shot.prompt` | string | 非空（纯空白算空） | 分镜提示词。台词直接写在这里，H3 会念出来并对上口型。`<Picture 1>`~`<Picture 7>` 对应 `characters` 的顺序 |
| `shot.seconds` | int | **3~15** | 镜头秒数，内部换算成 H3 的 17k+5 帧网格 |
| `shot.voice` | string | 必须在 `input/` 里 | 音色参考。给一段人声，角色就用这个音色说话 |
| `shot.steps` | int | **4~40** | 采样步数。8=试片，20=交付 |
| `shot.turbo` | bool | | 是否挂 turbo LoRA。只有 `steps<=8` 时才有意义 |
| `characters` | list | **1~7 个** | 每项要 `positive`（英文描述）；`name` 随便填；`seed` 建议给，**同角色全程用同一个**。可选 `view` 见下 |
| `voiceover` | object | 可选 | `{ "text": "...", "voice": "..." }`，`voice` 不给就沿用 `shot.voice`。`text` 上限 2000 字 |

### `characters[].view` —— 角色定妆照的视角

可选，不给就是 `正面全身像`。合法值就这五个，**写别的会静默回落到默认值**（不报错，很容易以为生效了）：

| 值 | 出图 |
|---|---|
| `正面全身像` | 全身，默认 |
| `侧面半身像` | 胸上半身 |
| `四十五度半身像` | 四分之三侧半身 |
| `面部特写` | 比头像更紧，切到脸中部 |
| `四视图拼图` | 2×2 四视图拼图 |

**拿资产的四视图不受 `view` 开关控制。** 每一镜的四个视角分支本来就会全跑
（拼图早就算出来了），所以不管 `view` 选哪个，都会**另外存一份 2×2 拼图**：

```json
"characters": [{"name": "智伯", "view": "正面全身像",
                "portrait": "E01_S01_智伯_定妆照.png",
                "four_view": "E01_S01_智伯_四视图.png",
                "four_view_download": "/file/E01_S01_%E6%99%BA%E4%BC%AF_%E5%9B%9B%E8%A7%86%E5%9B%BE.png"}]
```

- `four_view` —— **资产用的四视图**（2×2 拼图），下载路径在 `four_view_download`
- `portrait` —— 喂给视频生成的参考图，即 `view` 选中的那个视角

⚠️ **别把 `four_view` 当参考图喂 H3**：视频链路走的是 `portrait`。
把 2×2 拼图塞进 `input/` 当参考图会掉画质。四视图就当静态资产存着用。

给 `shot_id` 的话产物会按 `{shot_id}_{角色名}_{用途}.png` 重命名，方便直接归档。

> `prompt` 这一栏是接口契约；**提示词正文怎么写见 `prompting.md`**，
> 那里有实测过的硬规则（「导演指令词会被当台词念出来」等）和翻车案例。

**出参**（HTTP 202）

```json
{"job_id": "8a95fb071e1d", "status": "queued", "queue_depth": 1,
 "poll": "/task/8a95fb071e1d", "note": "一镜 20 步约 23 分钟, 8 步试片约 10 分钟"}
```

**入队前的校验**（返回 400，不占显卡、不产生任务）

| 错误信息 | 触发条件 |
|---|---|
| `请求体不是合法 JSON: ...` | body 不是 JSON |
| `'list' object has no attribute 'get'` | body 是数组不是对象 |
| `characters 不能为空` | 一个角色都没给 |
| `角色数 N 超过参考图口上限 7` | 超过 7 人 |
| `角色「x」缺 positive` | 某项没有 `positive` |
| `shot.prompt 不能为空` | 缺失、空串、纯空白 |
| `shot.voice 不能为空` | 缺失或纯空白 |
| `input/ 里没有「xxx」。现成的声线: ...` | 声线文件不存在，后面会列出实际可用的 |
| `shot.seconds=N 超出 3~15 秒` | 秒数越界 |
| `shot.seconds 要是整数, 收到 'abc'` | 类型错 |
| `shot.steps=N 超出 4~40` | 步数越界 |
| `voiceover.text 不能为空` | 传了 `voiceover` 但 `text` 空 |
| `voiceover.text N 字, 超过 2000` | 旁白太长 |

`voice` 会被 `basename` 处理，所以 `../../etc/passwd` 这种路径穿越不会读到 `input/` 外面。

---

## `GET /task/<job_id>`

```json
{
  "job_id": "8a95fb071e1d",
  "status": "done",
  "created": 1791063171.82,
  "error": null,
  "result": {
    "seconds": 421.0,
    "characters": [{"name": "智伯", "view": "正面全身像",
                    "portrait": "定妆照_正面全身像_00026_.png",
                    "four_view": "智伯_四视图_00001_.png"}],
    "video": "分镜视频_00020_.mp4",
    "ambient": null,
    "voiceover": null,
    "files": [{"role": "four_view", "label": "四视图",
               "file": "智伯_四视图_00001_.png", "size": 1187432}]
  },
  "elapsed": 421.0,
  "queue_depth": 1
}
```

| 字段 | 什么时候有 |
|---|---|
| `status` | 总是 |
| `queue_depth` | 仅 `queued` 时 |
| `elapsed` | `running` / `done` 时（秒） |
| `error` | `failed` 时，可读的中文原因 |

`status` 只有四种：`queued` → `running` → `done` / `failed`。

**`result.video` 存在不代表一定有视频**（历史上踩过：`SaveVideo` 把 mp4 报在
`images` 列表里，早先按 `videos` 取导致明明出了片却返回 `null`）。现在按扩展名归类，
拿到的就是真产物。`result.ambient` / `result.voiceover` 为 `null` 是正常的 ——
除非任务里带了 `voiceover`，H3 自带对白，不需要外挂。

产物落在 ComfyUI 的 `output/`，`result` 里给的是**文件名 + 可直接下载的路径**。

找不到 job 返回 404 `{"error": "没有这个 job"}`。

---

## `shot_id` 与产物命名

`result` 里每个产物都带一个 `*_download` 字段，那就是**下载接口的路径**，
已经百分号编码好了（中文文件名必须编码，HTTP 请求行按 latin-1 解码），
拼到 `$URL` 后面直接 GET 就行：

```json
{
  "result": {
    "video": "E01_S03_视频.mp4",
    "video_download": "/file/E01_S03_%E8%A7%86%E9%A2%91.mp4",
    "characters": [
      {"name": "智伯", "portrait": "E01_S03_智伯_定妆照.png",
       "portrait_download": "/file/E01_S03_%E6%99%BA%E4%BC%AF_%E5%AE%9A%E5%A6%86%E7%85%A7.png"}
    ],
    "voiceover": "E01_S03_旁白.flac",
    "voiceover_download": "/file/E01_S03_%E5%B9%A3%E7%99%BD.flac",
    "files": [
      {"role": "portrait", "label": "定妆照", "file": "E01_S03_智伯_定妆照.png",
       "renamed_from": "定妆照_正面全身像_00026_.png", "size": 983447},
      {"role": "voiceover", "label": "旁白", "file": "E01_S03_旁白.flac",
       "renamed_from": "tts/旁白_00001_.flac", "size": 231044}
    ]
  }
}
```

不传 `shot_id` 时保持 ComfyUI 原名（`分镜视频_00020_.mp4`）—— 但**生产环境
强烈建议传**，见下。

---

## 音频交付：两条路，别搞混

| | 走哪 | 产物 | 要不要后期 |
|---|---|---|---|
| **角色对白** | H3 自己生成，写在 `shot.prompt` 里的台词会被念出来并对上口型 | 在 `video_download` 那个 mp4 里 | **不要**，音画一体 |
| **旁白**（`voiceover` 字段） | 独立跑 IndexTTS2 | `voiceover_download` 指向的 `.flac` | **要**，自己叠到画面上 |

旁白是画外音，画面里没有人在说它，H3 没有这个表达通道，所以只能单独合成。
拿到 `.flac` 用 `ffmpeg -i 视频.mp4 -i 旁白.flac -c copy 输出.mp4` 叠上去即可。

**`voiceover` 为 `null` 说明这次任务没提交旁白** —— 不是接口坏了。
确认提交了 `{ "voiceover": {"text": "..."} }` 之后仍然为 `null`，才是真出问题。

---

## `GET /file/<name>`

下载产物。**必须带 token**（和其余接口一样）。

```bash
curl -s -H "Authorization: Bearer $TOK" "$URL/file/E01_S03_%E8%A7%86%E9%A2%91.mp4" -o shot.mp4
```

- 200 + 文件字节，`Content-Type` 按扩展名给（`video/mp4`、`image/png`、`audio/flac`…）
- 401 —— 没带 token
- 404 —— `output/` 里没这个文件
- 中文文件名走 `Content-Disposition: filename*=UTF-8''…`，客户端能正确落盘

只允许读 `output/` 目录内的文件：先取 basename，再 `realpath` 复核，
软链接指到外面也会被挡。

**没有这个接口整条生产链是断的** —— 出片之后没法把文件交给下游
（剪辑、审核、或作为下一镜的输入）。

---

## 为什么建议传 `shot_id`

ComfyUI 存出来的是 `分镜视频_00020_.mp4` —— 带自动计数器。跑一集几十镜之后：

- 名字和剧本的第几镜**对不上**
- 重跑一次就多一个计数器，没法判断哪个是最新版
- 下游拿到的文件名不可预测，没法自动化

传 `shot_id`（推荐 `集号_镜号`，比如 `E01_S03`）之后：

| 产物 | 命名 |
|---|---|
| 视频 | `E01_S03_视频.mp4` |
| 角色定妆照 | `E01_S03_智伯_定妆照.png` |
| 旁白 | `E01_S03_旁白.flac` |

`shot_id` 会被收拾成安全文件名（非字母数字下划线折成 `_`，最长 60 字符，
`../../etc/passwd` 这种会变成 `etc_passwd`）。**撞名不覆盖**，自动加 `-2`、`-3` ——
生产里静默覆盖旧片比报错更糟。

`files` 清单里保留了 `renamed_from`（ComfyUI 原名），出问题能回溯是哪次跑出来的。

---

## 建议的轮询节奏

- 提交后第一次查在 20~30 秒后（出图阶段约 30 秒/角色）
- 之后每 30~60 秒一次
- 8 步试片约 7 分钟，20 步交付约 16~23 分钟
- 轮询到 `done` 或 `failed` 为止

单次 HTTP 请求都是毫秒级的，网关的长连接超时掐不到 —— 这也是当初坚持异步的原因。
