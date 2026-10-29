# 思思壳（sisi-shell）

一台家用 NAS 上常驻的自主 agent，跑了一年不到的实录：**闸门、复盘、自我进化、出门发内容、每晚对账。**

不是框架，不追求通用。**它是一份「一个人怎么把 agent 养在一个会断电、会断网、只有 62G 内存的 NAS 上」的施工记录。**

## 先说清楚：同类项目已经很多

我不想假装自己是第一个。写这个之前查过，下面这些做得比我好：

| 项目 | 是什么 |
|---|---|
| [zhayujie/CowAgent](https://github.com/zhayujie/CowAgent) | 个人 AI 助手 + Agent Harness，会自进化、跑技能 |
| [EverMind-AI/Raven](https://github.com/EverMind-AI/Raven) | "harness of harnesses"，为递归自我改进建的常驻多 agent 生态 |
| [MemTensor/MemOS](https://github.com/MemTensor/MemOS) | 自进化记忆层，混合检索 |
| [microsoft/SkillOpt](https://github.com/microsoft/SkillOpt) | 把技能文档当可训练参数，留出门验收 |
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | agent 运行时，有循环检测与护栏 |
| [SAOS-3624/dsh-video-storyboard](https://github.com/SAOS-3624/dsh-video-storyboard) | 视频分镜（我看视频用的就是它） |

**那为什么还发？** 因为上面这些里，我没找到一个同时包含这几件事的：

1. **家用 NAS 上的真实运维**：systemd 常驻、断电重来、内存 62G、两个浏览器四个调试口
2. **每晚对账**：不是对钱，是把两边（她和另一个我）踩的坑摊开对——**重复的、被冲掉的、没解决的**
3. **「被冲掉检测」**：她进化出来的规则被一次部署冲掉过，之后每次都对快照比对条数
4. **出门流水线**：配音按参考样本逐项量出来调、封面头、出厂检查（首帧亮度/响度/时长）
5. **规矩带日期和起因**：每条规则都写「为什么加、哪次事故换来的」

## 内容

```
shell/     agent 循环、闸门、工具、进化、对账、数据回收
docs/      技术总览、脱敏后的规则补丁（能看到每条规则怎么来的）
```

## 五层结构（详细见 docs/技术总览.md）

```
① 静态前缀  一个 token 都不动（保 KV Cache）
② 轨迹      只追加；状态栏永远在末尾
③ 闸门      先验后做：参数/路径/风险/熔断/原地打转，全在门口拦
④ 反馈      工具返回真实结果；拿不到证据就不算完成
⑤ 复盘      打分 → 提案 → 快照 → 应用 → 用后续分数验证 → 无效回滚
```

## 借了什么，不装原创

- Harness 分层、故障四分类、进化闭环 —— 照《深入理解 AI Agent》做的
- 技能优化的留出门 / 被拒缓冲 / 字数预算 —— 抄 microsoft/SkillOpt
- 视频分镜 —— 用 SAOS-3624/dsh-video-storyboard，顺手上报了一个 `video_zoom` 丢参数的 issue

**自己的部分**：闸门这套组合、语义检索 + 条目级去重、对账与问题账本、出厂检查与封面头，以及那一堆踩坑换来的规则。

## 纪律

- 规则只加不改历史：每条带日期与起因，删了要写为什么
- 日志不撒谎：失败、花了多少、被拦几次，一个数都不编
- 拿不到证据就说不确定

## License

MIT
