# 节点十二、十三联合结论

- 节点十二：**PASS**。Mac M4 arm64 生命周期八项通过；Windows 复用原执行方五项及独立正常退出重开回执。
- 节点十三：**PASS**。按用户确认的同代码树口径核证；两个平台完整源码 SHA 不同，实际身份分别保留。
- 节点十四：**NOT_STARTED**。正式分发渠道尚未执行或核证；Windows 签名不作为要求，现有包如实标记未签名。
- 节点十五：**NOT_STARTED**。尚无客户签收回执。

## 实际候选

| 平台 | 版本 | 完整源码 SHA | 构建 |
| --- | --- | --- | --- |
| Mac M4 arm64 | 1.0.0.6 | c5e066acff7f50edf5f1e506abcca33372cc6033 | 38730362964 |
| Windows x64 | 1.0.0.6 | 7102b713df1136ae83848eed5814a60ede66a355 | local-windows-longpath-20261015-114026 |

共同 Git tree：`60aef1efa8c18fb01cea7c7234716c2e5b758671`。Windows 源码提交是 Mac 合并提交的直接父提交。

Windows 本次核证复用了原执行方发布回执；未在本机独立读取 Windows 全部本地原件、重新计算安装包哈希或重跑实机验收。普通业务、本轮 Intel Mac、正式发布和客户签收不在已通过结论内。

## 原件

- [联合核证正式报告](node13-joint-verification-final.json)
- [Mac 实机验收报告](mac-c5-lifecycle-final.json)
- [源码与候选对照](node12-node13-candidate-reconciliation.json)
- [当前文件引用一致性检查](final-report-reference-consistency.json)
- [Windows 原执行回执一](https://github.com/42433422/XCMAX/pull/2340#issuecomment-6190996826)
- [Windows 原执行回执二](https://github.com/42433422/XCMAX/pull/2340#issuecomment-6191186660)

历史报告按原字节保留在同目录 `history/`；本次仅修正文件引用，未重跑实机。十四、十五状态为联合报告签发时状态，后续工作另以新回执记录。
