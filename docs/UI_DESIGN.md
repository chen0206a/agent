# 界面设计参考

本次只调整视觉样式，保留订单、申请状态、权限、审批和 Agent 业务行为。

## 参考与许可

- [aftabrehan/apple-landing-v2](https://github.com/aftabrehan/apple-landing-v2)，MIT，参考版本 `f7298dba92b15cbc2e85b875ef69ec52d37dc61d`。该仓库已归档，作为设计参考而非运行依赖。
- 借鉴 `src/styles/colors.scss` 的中性色与蓝色强调体系，以及 `src/components/header/Header.module.scss` 的半透明导航和 `saturate(180%) blur(20px)` 效果。适配实现在 `frontend/src/app/apple-inspired.css`，许可全文见 [MIT notice](licenses/apple-landing-v2-MIT.txt)。
- [adrianhajdin/iphone](https://github.com/adrianhajdin/iphone) 作为候选考察：以 GSAP / Three.js 产品展示为主，未引入其代码或依赖。

未复制 Apple 标志、产品图片、视频或专有字体；使用现有图标与系统字体。本项目与 Apple 无关联。

## 适配方式

采用灰白背景、深灰文字、蓝色操作按钮、白色圆角卡片和轻量阴影；透明效果限定在导航区域。保留成功、待处理和拒绝状态的语义色。客户页面强调阅读与申请状态，管理员页面保留表格和政策证据密度。小屏保持原导航结构，支持键盘焦点与 reduced-motion。

截图来自本地隔离脚本模型的真实页面，不代表生产业务或真实模型评测。历史评测文件保持原样。

## 验证

前端组件测试 5/5、浏览器 E2E 8/8、lint 和生产构建通过。检查登录、客户聊天、高额审批和 390px 手机截图；结果见 [验证记录](verification/ui-refresh/summary.json)。后端、冻结评测数据和历史实验文件未改动。
