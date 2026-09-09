# TEMP：Unity 收到 RSV1、但收不到 SMV2

> 暫存問題紀錄；本檔不修改 bridge、fitter、UDP protocol 或 safety gate 行為。

## 現象

Unity `SMPL 0901 Live Player` 已按下 `Start Receiving`，畫面顯示：

```text
SMV2 0.0.0.0:9095 LISTENING 0.0 FPS age --
observed=--, acceptedFrom=--, received=0, accepted=0, ignored=0, decodeErrors=0

RSV1 0.0.0.0:9096 LISTENING
observed=192.168.1.250, acceptedFrom=192.168.1.250, received=78, accepted=78

Pose apply: waiting for SMV2; applied=0, heldInput=0
```

因此 Raw 59pt Skeleton 有資料，但 Show Fitted Skeleton 與 SMPL Mesh 不會更新。

## 已釐清

1. Unity 的 9095 receiver 已成功 bind，沒有 decode error 或來源 IP filter rejection。
2. RSV1 能從 `192.168.1.250` 到達同一台 Unity 主機的 9096，表示該路徑與 Windows 防火牆基本可用。
3. Fitted Skeleton 是從 Unity 已套用 SMV2 後的 runtime bones 畫出；它和 Mesh 同時不動是預期的共同症狀，不是 fitted renderer 單獨故障。
4. Unity 的 `SMV2 received=0` 表示封包沒有抵達 socket，問題發生在 Unity pose application 之前。

## Bridge log 證據

伺服器 log 的候選幀持續為：

```text
accepted:false
action:"hold_previous"
reasons:["twist>100deg"]
```

部分範例：

| frame | fit residual | facing mismatch | worst twist | reasons |
|---:|---:|---:|---:|---|
| 32024 | 138.1 mm | 49.2° | 179.8° | residual、twist |
| 32026 | 128.0 mm | 10.2° | 156.8° | residual、twist |
| 32027 | 98.2 mm | 1.3° | 140.5° | twist |
| 32029 | 62.3 mm | 0.9° | 162.5° | twist |
| 32030 | 105.8 mm | 0.4° | 144.7° | residual、twist |

至少 frame 32027、32029 的 residual 與 facing 沒超過目前門檻，但仍被 twist 門檻攔截。因此 bridge 沒有呼叫 SMV2 send，Unity 9095 保持 `received=0`。

## 待伺服器端確認

請在實際部署主機確認完整統計與啟動參數：

```bash
docker compose logs --tail=200 bridge \
  | grep -E 'calibrating|calibration complete|distortion|received=|sent=|held='

docker compose config | grep -E 'unity-host|unity-port|max-fit|max-twist|max-delta|max-facing'
```

需要確認：

- 校正是否已完成。
- `sent` 是否一直為 0、`held` 是否持續增加。
- 所有幀是否都被同一個 safety reason 擋下。
- 實際 container 的 `--unity-host` 是否是 Unity 可接收的 IP、`--unity-port` 是否為 9095。
- twist diagnostic 對目前 SMPL local joint axes 是否存在系統性假陽性。

## 邊界

此問題紀錄不主張直接修改或停用伺服器 safety gate。是否調整 twist 判定、門檻或發送策略，應在伺服器部署環境以完整輸入、mesh 與 log 驗證後決定。
