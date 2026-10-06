---
name: ADL_comfyui_skill
description: 通过 HTTP API 调用 AutoDL 上部署的历史短剧视频生成服务（ComfyUI + MiniMax-H3），提交一镜任务并拿到带对白与口型的 mp4。当用户要生成历史短剧/古装短剧/分镜视频/带台词的镜头、要把剧本或人物设定变成视频、要提交或查询视频生成任务、要批量出片、或提到"短剧""分镜""出片""出图""口型""智伯""角色定妆照"或这套服务的 job_id / 队列 / token 时，都用这个 skill。只要涉及"用那个接口生成视频"或"跑一镜"，即使没直接说 API，也应先读这里。
---

# 历史短剧视频生成（AutoDL + ComfyUI + H3）

这套服务把「一条历史短剧镜头」变成一支**带对白 + 环境音 + 口型**的 mp4。
你拿到的是结构化任务数据，交给接口，最后拿产物文件名。

**先读这一页就能跑通。** 需要更细的字段说明时再去读 `references/`。

---

## 一、开工前必须确认的三件事

别急着提交。先把这三样问清楚，缺哪样就问用户：

| 要确认 | 怎么拿 | 缺了会怎样 |
|---|---|---|
| **服务地址** | `https://<域名>:<端口>` | 提交直接 404 |
| **token** | 用户给的；或服务器上 `shot_token.txt` 的第一行 | 提交返回 401 |
| **这一镜要谁出场、说什么** | 用户的剧本 / 人物设定 | 没法构造任务 |

拿不准地址或 token 就先探活，比瞎猜快：

```bash
curl -s -H "Authorization: Bearer $TOKEN" "$URL/health"
```

- 返回 `{"ok": true, ...}` → 地址和 token 都对
- `401` → token 错了
- 404 / 连不上 → 地址或端口不对（AutoDL 只映射 6006/6008，端口对不上就是 404）

---

## 二、跑一镜的完整流程

```bash
# 1) 拿模板（voice 会自动填成 input/ 里真实存在的文件）
curl -s -H "Authorization: Bearer $TOKEN" "$URL/example" -o task.json

# 2) 改 task.json：characters 换成人，出场的人有几个给几个（最多 7）
#    每个人的 seed 一定要错开 —— 同种子同描述会长得一样
#    写台词：写在 prompt 里，H3 会念出来并对上口型

# 3) 提交，立刻返回 job_id
curl -s -X POST "$URL/task" -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' -d @task.json
# -> {"job_id":"...","status":"queued","queue_depth":1}

# 4) 轮询。20 步一镜约 16 分钟，8 步试片约 7 分钟
curl -s -H "Authorization: Bearer $TOKEN" "$URL/task/<job_id>"

# 5) status=done 时 result.video 是产物文件名；result 里有 *_download 字段，
#    那是下载路径，拼到 $URL 后面 GET 就能把文件字节拿下来
# 6) 下一镜要拿上一镜的图当输入时，同样走 /file/ 下载到本地再提交
```

**生产环境务必传 `shot_id`**（推荐 `集号_镜号`，如 `E01_S03`）。不传的话产物叫
`分镜视频_00020_.mp4` 这种带自动计数器的名字 —— 一集几十镜之后完全对不上剧本，
重跑也分不清哪版是新的。传了之后产物是 `E01_S03_视频.mp4`、`E01_S03_智伯_定妆照.png`，
撞名自动加 `-2` 不覆盖旧片。

**直接用 `scripts/shot_client.py` 更快** —— 提交、轮询、收产物都包好了：

```bash
python scripts/shot_client.py --url "$URL" --token "$TOKEN" \
       run --script shot.json --out ./产物/结果.json
```

（子命令是 `health` / `example` / `submit` / `wait` / `run`，不是长选项。）

---

## 三、构造任务：字段速查

```jsonc
{
  "shot": {
    "prompt": "中近景, 腰以上构图, 面部清晰占据画面三分之一. <Picture 1> 中的男子面色沉下来, 低声说: 你孤掌难鸣, 今日便是你的死期. 电影镜头缓慢推近. 声音: 男声, 庭院环境音, 风声.",
    "seconds": 5,          // 3~15 整数
    "voice":   "zhibo.mp3",// input/ 里的声线文件, 不存在直接 400
    "steps":   20,         // 4~40。20=交付档, 8=试片档
    "turbo":   false       // steps<=8 时才设 true
  },
  "characters": [
    { "name": "智伯",   "positive": "adult man in his fifties, short stubble beard, bare chin and bare upper lip, dark red ceremonial robe, full body, cinematic still", "seed": 42 },
    { "name": "赵襄子", "positive": "middle aged woman, grey hair tied up, pale jade hairpin, deep green silk robe, full body, cinematic still", "seed": 43 }
  ],
  "voiceover": { "text": "旁白...", "voice": "narrator.mp3" }   // 可选
}
```

`characters` 的第 i 个对应 prompt 里的 `<Picture i+1>`。**谁出场写谁的编号**，
没出场的人别列进去（列了也会占一个参考图口）。顺序从 1 连续编。

---

## 四、提示词：先读 `references/prompting.md`

调用方不知道这套提示词怎么写，照着编会出不了东西。**动手构造 prompt 之前
先读那份**，里面有实测过的硬规则，其中三条最容易翻车：

1. **导演指令词不能单列** —— 写了「停顿」，H3 会把"停顿"两个字**当台词念出来**。
   演法要写进句子：`他面色沉下来, 低声说: ...`
2. **有台词的角色嘴要露出来** —— 出图时下巴被胡须盖住，视频里口型就一个字都
   看不见。`positive` 里写 `short stubble beard, bare chin and bare upper lip`
   这种具体名词才有效，`neatly trimmed` 压不住。
3. **景别要写明** —— 不写就经常出大远景，人物小到看不清，口型无从谈起。
   写「中近景, 腰以上构图」。注意「缓慢推近」是镜头运动，替代不了景别。

另外：`negative` 入参**不生效**（被清零 + cfg=1），要控制画面只能写 `positive`。

参数字段的完整语义和边界见 `references/api.md`。

---

## 五、生产怎么排

单卡一次只能跑一镜，并发提交只会互相抢显存。所以**一次一镜，排着来**。

| 场景 | steps | turbo | 一镜 5 秒耗时 |
|---|---|---|---|
| 试片 / 看构图对不对 | 8 | true | 约 7 分钟 |
| **交付** | 20 | false | 约 16 分钟 |

**先用 8 步试一镜确认人物和构图，再切 20 步出交付片。** 20 步慢一倍多，
但画面、口型、人声全面更好；8 步多人同框口型会崩，只适合试片。

一镜 20 多分钟的等待里，别空转 —— 下一镜的 `characters` 可以先写好。

排一整集的顺序建议：先出全部角色定妆照（每张 30 秒）确认脸对，
再逐镜出视频。人设要在整集里保持一致，**同一个角色的 positive 和 seed 全程不要改**。

---

## 六、出错了怎么办

服务在入队前会挡掉一批错，返回 400 且**不占显卡**：

| 现象 | 原因 | 怎么办 |
|---|---|---|
| 401 | token 错或没带 | 确认 `Authorization: Bearer` 头 |
| 404 | 地址/端口不对 | AutoDL 只映射 6006/6008，服务跑在别的端口上公网就是 404（不是服务没起）。用 `ss -lntp` 看服务实际监听哪个端口，再和控制台「自定义服务」的配置比对；最快的办法是在两个端口上各起一个只回一句话的探针，能从公网访问到的那个就是映射配的 |
| 400 `seconds` 越界 | 超 3~15 | 改 `shot.seconds` |
| 400 `input/ 里没有「xxx」` | 声线文件名错 | 用 `/example` 返回的 `_note` 里的文件名 |
| 400 `角色数 N 超过上限 7` | 一镜超过 7 人 | 拆成两镜 |
| `status: failed` | 采样阶段出错 | 看 `error` 原文；重试一次，还失败就报给用户 |

轮询时 `status` 只会是 `queued` / `running` / `done` / `failed`。
`running` 就是正常在跑，别急着重复提交 —— 重复提交会占掉后面所有人的位置。

---

## 七、边界（这些别踩）

- **一次一镜。** 单卡，第二个任务会排队（`queue_depth` 告诉你排第几）。
- **每镜最多 7 个角色**，受 H3 参考图口限制。
- **每个角色的 seed 必须不同**，否则同描述的人会长得一样。
- **别传超范围的 `seconds` / `steps`**，服务端会挡；硬传会把唯一那条显卡占死。
- **服务重启会中断正在跑的任务**，它会被标成 `failed`，重新提交即可。

---

## 八、深入阅读

| 文件 | 什么时候读 |
|---|---|
| `references/prompting.md` | **写提示词之前必读** —— 实测过的硬规则和翻车案例 |
| `references/api.md` | 要确认字段边界、错误码、或写自动化脚本 |
| `references/production.md` | 批量出片、整集排期、质量档位取舍、故障排查 |
| `scripts/shot_client.py` | 想直接跑而不是手搓 curl |
