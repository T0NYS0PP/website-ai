# TWO — kinetic typography film

参考動画（snapgram スタイル）に合わせて作った TWO のブランドムービーのレンダラー。
Python（Pillow + numpy）でフレームを生成し、ffmpeg で H.264 に書き出す。
MV 素材（Google Drive「TWO MV」）の人物を切り抜いてサーマル（熱画像風）シルエットにしている。

## 出力

- `out/TWO_mv_1440x1080_hq.mp4` — 4:3 / 24fps / 21.8s マスター（高画質）
- `out/TWO_mv_1440x1080.mp4` — 共有用の軽量エンコード
- `out/TWO_mv_960x720.mp4` — 参考動画と同じ解像度
- `out/TWO_mv_contact.png` — 1秒ごとのサムネイル

（mp4 は .gitignore 済み。下のコマンドで再生成できる）

## 構成（秒）

| 時間 | シーン | 素材 |
|---|---|---|
| 0.0 – 0.55 | 赤いカードに巨大な「TWO」、破線ガイド、ピクセルグリッチ | |
| 0.55 – 3.45 | 紙地。「TWO began with one question:」を単語ごとにタイプ、"question:" に手描きの下線 | |
| 3.45 – 6.25 | 「what does it really mean to create?」、"create?" を手描きの丸で囲む | |
| 6.25 – 9.65 | 黒地 + サーマルシルエット。「Not clothes for the sake of clothes.」 | 01.mov 2.6s〜（歩き、左右反転） |
| 9.65 – 13.05 | 「but something intentional,」→「made with purpose.」黒から白へ転じ、シルエットが影に冷える | 04.mov 1.0s〜（椅子、正面） |
| 13.05 – 16.45 | 紙地に T / W / O の文字が漂い、赤い走り書きの丸。「Each piece carries that search.」 | |
| 16.45 – 19.85 | 黒地 + サーマル。「I hope it resonates with you too.」 | 10.mov 4.6s〜（立ち姿、左右反転） |
| 19.85 – 21.8 | 紙地に巨大な「TWO」のアウトロ、"made with purpose." | |

## 再生成

```
# 素材を Drive から取得（環境の Allowed domains に drive.google.com と
# drive.usercontent.google.com が必要）
./fetch_drive.sh

# 人物切り抜き用（任意。無いときは背景差分にフォールバック）
python3 -m venv ../../.segenv && ../../.segenv/bin/pip install "rembg[cpu]"

# レンダリング
../../.segenv/bin/python render_two.py out/TWO_mv_master.mp4 --footage footage \
  --clips "01.mov@2.6:flip:scale=1.5:y=0.12,04.mov@1.0:scale=1.4:y=0.22,10.mov@4.6:flip:scale=1.15:y=0.03"
```

`--clips` の書式: `NAME@IN点秒[:flip][:scale=1.25][:y=0.04][:method=auto|rembg|plate|key][:model=u2net]`

- `flip` 左右反転（人物がテキストの方を向くように）
- `scale` フレーム高さに対するクリップの拡大率（上下はトリミング）
- `y` トリミング窓の開始位置（拡大後クリップに対する割合）
- `method` 切り抜き方法。auto は rembg があればそれを、無ければ背景差分（固定カメラで人物が動くカット向け）
- 切り抜き結果は `footage/.cache/*.npy` にキャッシュされるので、2回目以降のレンダリングは速い

素材の確認用に `./make_sheets.sh` で 480p のプロキシとタイムコード付きコンタクトシートを `proxies/` に作れる。

## 必要なもの

- Python 3 + Pillow + numpy（切り抜きには rembg + onnxruntime）
- ffmpeg
- Inter フォント（`/usr/share/fonts/opentype/inter/`）
