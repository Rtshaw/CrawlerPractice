# 包裹運費寫入 Google Sheet GUI

這個工具把「包裹清單 -> Gmail 找訂單號 -> Google Sheet 工作表 H2 寫入運費」做成可重用 GUI。

## 執行

```powershell
& 'C:\Users\woman\.pyenv\pyenv-win\versions\3.11.9\python.exe' -m tools.package_shipping_gui
```

## 打包成 exe

```powershell
& 'C:\Users\woman\.pyenv\pyenv-win\versions\3.11.9\python.exe' -m tools.package_shipping_gui.build_exe
```

輸出位置：

```text
dist/package_shipping_gui/package_shipping_gui.exe
```

這個工具使用 Tkinter GUI；在這台 pyenv-win 環境中，onefile 版本會因為 Tcl/Tk 解壓到 `%TEMP%` 而無法啟動，所以打包腳本使用穩定的 onedir 形式。請從整個 `dist/package_shipping_gui/` 資料夾裡執行 `package_shipping_gui.exe`。

GUI 會開啟後：

1. 貼上包裹清單。
2. 填 Google Sheet URL。
3. 填運費，例如 `58`。
4. 按 `解析預覽`。
5. 確認每列都是 `ready` 後按 `寫入 H2`。

## Google OAuth

第一次使用 Python 直接連 Gmail / Sheets 時，需要 Google OAuth client secret：

- 放在 `tools/package_shipping_gui/.local/credentials.json`
- OAuth token 會存在 `tools/package_shipping_gui/.local/token.json`
- `.local/` 已加入 `.gitignore`，不要提交這些檔案。

如果使用打包後的 exe，放在：

- `dist/package_shipping_gui/.local/credentials.json`
- token 會存在 `dist/package_shipping_gui/.local/token.json`

需要的套件：

```powershell
& 'C:\Users\woman\.pyenv\pyenv-win\versions\3.11.9\python.exe' -m pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

## 安全行為

- `解析預覽` 不寫入 Google Sheet。
- `H2` 非空時預設 blocked，不覆寫。
- 勾選 `允許覆寫非空 H2` 才會讓非空 H2 進入 ready。
- 找不到信件、找到多個訂單號、找不到工作表、找到多個工作表，都會 blocked。
- 寫入後可以再按一次 `解析預覽` 讀回確認。
