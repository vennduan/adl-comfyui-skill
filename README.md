# ADL_comfyui_skill

给**外部 AI** 用的技能包：教它怎么调 AutoDL 上部署的历史短剧视频生成服务，
以及怎么把一集排出来。

## 装到哪

Claude Code：拷进项目的 `.claude/skills/` 或全局的 `~/.claude/skills/`。
其它支持 skill 规范的 AI 同理，认 `SKILL.md` 的 YAML frontmatter 就行。

```bash
cp -r ADL_comfyui_skill ~/.claude/skills/
```

## 结构

```
ADL_comfyui_skill/
├── SKILL.md                 主文件：怎么调、怎么排产、踩过的坑
├── references/
│   ├── prompting.md         分镜提示词怎么写（实测硬规则，必读）
│   ├── api.md               API 契约：字段边界、错误码、返回值
│   └── production.md        生产规范：排期、档位、故障排查
├── scripts/
│   └── shot_client.py       命令行客户端（只用标准库）
└── evals/
    └── evals.json           测试用例
```

`SKILL.md` 保持精简（按需展开），细节都在 `references/` 里 —— 这样触发时
只占几百 token 的上下文。

## 用法

```bash
export ADL_URL='https://<域名>:<端口>'
export ADL_TOKEN='<token>'

python scripts/shot_client.py health                        # 探活
python scripts/shot_client.py example                       # 拿可提交的模板
python scripts/shot_client.py run --script shot.json        # 提交+轮询到底
python scripts/shot_client.py wait --job <job_id>           # 只查某次任务
```

## 维护

改了服务行为（字段、错误码、端口、档位耗时）之后，这三处要同步：
`SKILL.md` 的速查表、`references/api.md` 的契约表、本目录的 `scripts/shot_client.py`。
三处不一致的话，AI 会按旧的说法调，然后卡在一个已经改掉的错误上。
