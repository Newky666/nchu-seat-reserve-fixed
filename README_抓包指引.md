# 小米平板抓包图文指引

> 目的：拿到图书馆预约系统的关键登录信息 —— `auth`、`uid`、`seatBookers`、座位 id。
> 全程约 5 分钟，跟着点即可，不需要任何技术基础。

---

## 第一步：下载抓包工具

在小米平板自带的「应用商店」或浏览器里搜索 **「Reqable」**，下载安装。

> 备选：如果装不了 Reqable，可以搜 **「HttpCanary」（小黄鸟）**，用法几乎一样。

## 第二步：开始抓包

1. 打开 Reqable，点首页 **「开始抓包」**（或底部中间的大按钮）
2. 首次会弹出提示，点 **「允许」** 授予 VPN 权限
3. 如果提示安装 **CA 证书**，按它的引导点「安装」即可（安卓装证书很简单，一路确认）

## 第三步：在微信里预约一次座位

保持抓包开启，切换到**微信**：

1. 进南昌航空大学图书馆公众号 → 「我的微图」→「座位预约」
2. 正常操作一次：选座位 → 选时间段 → 提交预约（怕占座的话提交后可以再取消，不影响抓包）
3. 确保页面成功提交过一次预约

## 第四步：导出抓包结果（两种方式，推荐方式一）

### 方式一：复制 cURL（最推荐，最省事）

1. 回到 Reqable，点 **「停止抓包」**
2. 在请求列表里找到网址带 **`bookSeats`** 的那条请求（可点搜索图标搜 `seat`）
3. **点开**这条请求 → 找 **「复制」** 或 **「分享」** 按钮 → 选 **「cURL」**（或「复制为 cURL」）
4. 复制到的就是一段以 `curl` 开头的文本，形如：

```
curl 'http://lib-zw.lib.nchu.edu.cn/Seat/Index/bookSeats?LAB_JSON=1' \
  -H 'Cookie: auth=xxx; uid=yyy; is_remember=zzz' \
  --data-raw 'beginTime=...&seats[0]=61078&seatBookers[0]=289306'
```

5. 把这段 cURL 文本**保存成 `.txt` 文件**（微信「文件传输助手」发到电脑，或直接发给我都行）

### 方式二：导出 HAR 文件

1. 回到 Reqable，点 **「停止抓包」**
2. 在请求列表里找到网址带 **`bookSeats`** 的请求
3. 长按这条请求 → 选 **「导出」** → 导出成 **HAR 文件**
4. 通过 **微信「文件传输助手」** 发到电脑

> 两种方式二选一即可，程序都能自动解析。

## 第五步：把文件交给程序

把 cURL 的 `.txt` 文件（或 `.har` 文件）放到电脑的项目目录 `d:\code\nchu-seat-reserve-fixed\`，然后任选一种方式导入：

### 图形界面（推荐）

双击 `seats_bookishere.bat`（或 `py gui.py`）打开程序 → 点顶部 **「导入抓包文件」** → 选择该文件。

### 命令行

```powershell
cd /d D:\code\nchu-seat-reserve-fixed
py main.py --import 你的文件.txt
```

程序会自动解析出 `auth`、`uid`、`seatBookers`、学号、座位 id，写进 `config.json`，**不用手动复制**。看到类似输出即成功：

```
[OK] 已导入认证信息:
  学号       : 2404xxxx
  auth       : xxxxxxxx...
  uid        : xxxxxxxx...
  seatBookers: xxxxxx
  座位 id    : xxxxx
```

---

## 常见问题

**Q：抓不到 HTTPS 请求？**
A：看 CA 证书装没装。安卓在 设置 → 安全 → 加密与凭据 里能看到 Reqable 的证书就说明装好了。

**Q：找不到 bookSeats 这条请求？**
A：确认预约真的提交成功了。在 Reqable 里搜索 `seat` 或 `book`。

**Q：复制 cURL 时找不到「复制为 cURL」选项？**
A：点开请求详情，把 **URL + Headers + Body** 三部分**截图**发我也一样能解析。或者用方式二导出 HAR。

**Q：cURL 里没包含学号怎么办？**
A：只要 cURL 里 `Cookie` 和 `--data-raw` 参数齐全（含 `seats[]`、`seatBookers[]`），auth/uid/座位都能提取。学号若提取不到，导入后可在界面「用户ID」看到默认学号，不影响预约。

**Q：抓完包需要卸载证书吗？**
A：可以。在 设置 → 安全 → 加密与凭据 里删掉 Reqable 证书即可，不影响已抓到的结果。
