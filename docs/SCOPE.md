# 职航 CareerFlow｜首版范围与验收

2026-11-11，用户明确把原个人求职研究提升为面向所有求职者的通用平台开发。学生、应届生、社会招聘、转岗求职均使用独立个人档案；个人学历、届别、学校、岗位不写进产品规则。已有杨炜晨材料不自动公开或作为默认种子。

## 必须贯通的链路

用户档案与有出处的经历 → 可扩展搜索及企业官网源 → 采集、去重、更新、过期与证据 → 硬条件与职责匹配 → 针对岗位生成DOCX/PDF → 投递工作台 → 有来源的回执、消息和面试准备。

第一版实际能力按证据区分：公开招聘API、JSON-LD招聘网页、企业公告链接发现、用户自带搜索API、用户自带模型API、SMTP投递和IMAP回信、需要原站登录的手动申请。不能把浏览器内部接口称为已获官方授权API，也不能把招聘方API密钥当成求职者普遍拥有的能力。

## 数据与授权

独立账号隔离档案、API密钥、岗位、文件、邮件和计划。密钥加密保存在运行数据目录，源码与公开预览无密钥/用户私密档案。默认只监听本机；多用户公网部署另需TLS、资源限制、身份与运营检查。

公开采集是只读。采集源保存原URL、检查时间、原文散列及状态；未获得正文不得显示已核实。未披露薪资/福利保持未知。截止日期和最后检查时间不是同一字段。

自动邮件投递必须有用户配置的发送邮箱、明确收件地址和已生成附件。重复投递受唯一约束保护；发送结果不明确不自动重试。SMTP接受、企业回执、用户手动报告和HR回应分别记录。

测试使用虚构标明的档案与受控测试接收端；不会向真实企业投递虚构身份。用户已选择自己的测试邮箱，配置入口已提供，真实收发尚待用户接入。真实企业收件/回复与本地协议测试不能混写。

## 重要接口参考（本轮已读）

- https://github.com/shengjidaguai-china/BossHunter/blob/main/docs/FAQ.md
- https://github.com/shengjidaguai-china/BossHunter/blob/12d6891ef7db59970019e1b5ad238a4bbe7f2e5c/src/bosshunter/collection/capabilities.py
- https://docs.greenhouse.io/job-board.html
- https://github.com/lever/postings-api
- https://developers.ashbyhq.com/docs/public-job-posting-api
- https://histatic.zhipin.com/front/bosshi-mp-docs/service/ready/apiCall/callProcess/processOverview.html
- https://help.sap.com/docs/CPS/5e4b52c7b81340b6a091b8c8d2e487af/cd0afca50bf34c42bdfa2ac12f197630.html

BossHunter为PolyForm Noncommercial 1.0.0；本项目独立实现，不复制其代码，不把它作为MIT依赖。官网源/平台权限具有时效性，接入矩阵须明确日期和测试层级。

## 验收门槛

1. 至少三种公开接口/页面来源实际拉取，保留真岗位与检查证据；所有来源失败可见。
2. 不同档案、毕业届别、学历和经验的匹配结果不同；已关闭和届别不符不能自动投递。
3. 生成附件来自本人确认的事实，未经确认的事实不进入简历；输出可编辑且可提取文字。
4. 账户间不能读取岗位、密钥、简历、消息；外网URL不能访问本地/内网地址。
5. 定时任务持久保存、失败退避、重启恢复；定时采集和邮件发送不共用盲目重试规则。
6. 真实邮件链路须以实际服务回执与收信为证；没有接入凭据前明确未验收。
7. 页面交互、移动布局、下载、错误处理与恢复实际测试；演示入口明确只读样例。
