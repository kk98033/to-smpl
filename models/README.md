# 模型檔放置方式

目錄最後應為：

```text
models/
├── J_regressor_body25.npy       # 已隨此專案提供
├── best_ckpt.pth.tar            # adaptive-fast neural prior；不納入 Git
├── smpl/
│   └── SMPL_NEUTRAL.pkl         # SMPL body model
└── smplx/
    └── SMPLX_NEUTRAL.npz        # Dashboard SMPL-X body/hand preview；不納入 Git
```

`SMPL_NEUTRAL.pkl` 已包含於這份私人 repository，並透過 Git LFS 管理。程式只使用 neutral SMPL；檔名及大小寫必須完全一致。

clone 時必須安裝 Git LFS，否則只會取得一個 pointer 檔：

```bash
git lfs install
git lfs pull
```

此檔仍受 SMPL 授權條款限制。請保持 repository 私有，不要把 repository、release artifact 或模型檔公開散布。

下載頁：<https://smpl.is.tue.mpg.de/>


## SMPL-X Dashboard 模型

Dashboard 的 **SMPL-X** 頁籤需要官方 neutral locked-head NPZ。由下載壓縮檔
擷取並放在下列固定位置：

```bash
mkdir -p models/smplx
unzip -j /path/to/smplx_lockedhead_20230207.zip \
  models_lockedhead/smplx/SMPLX_NEUTRAL.npz \
  -d models/smplx
sha256sum models/smplx/SMPLX_NEUTRAL.npz
```

本次驗證檔 SHA-256：

```text
43d8f3a1375d7c5baae207870a5d51def0f7e6b507df709b4937598b5e7d965d
```

此模型只用於 Bridge 產生 Dashboard 診斷表面；Unity 的 SMV2/RSV1 UDP
協定不變。`models/smplx/` 已由 `.gitignore` 排除，不可提交或公開散布。

## Adaptive-fast checkpoint

正式預設 `adaptive-fast` 另需 Learnable-SMPLify Body25 checkpoint：

```bash
cp /path/to/licensed/best_ckpt.pth.tar models/best_ckpt.pth.tar
sha256sum models/best_ckpt.pth.tar
```

本次驗證檔 SHA-256：

```text
ae3ff40bfab93a339ce6f1da53194d667c2812d14d182fa619a6c32736056e35
```

checkpoint 已由 `.gitignore` 排除，不可提交或公開散布。若暫時沒有該檔，可用 `SMPL_SOLVER_PROFILE=quality` 啟動保留的舊 optimizer。
