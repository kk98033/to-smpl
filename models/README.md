# 模型檔放置方式

目錄最後應為：

```text
models/
├── J_regressor_body25.npy       # 已隨此專案提供
└── smpl/
    └── SMPL_NEUTRAL.pkl         # 私人 repository 透過 Git LFS 保存
```

`SMPL_NEUTRAL.pkl` 已包含於這份私人 repository，並透過 Git LFS 管理。程式只使用 neutral SMPL；檔名及大小寫必須完全一致。

clone 時必須安裝 Git LFS，否則只會取得一個 pointer 檔：

```bash
git lfs install
git lfs pull
```

此檔仍受 SMPL 授權條款限制。請保持 repository 私有，不要把 repository、release artifact 或模型檔公開散布。

下載頁：<https://smpl.is.tue.mpg.de/>
