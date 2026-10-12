# TWO — kinetic typography film

参考動画（snapgram スタイル）に合わせて作った TWO のブランドムービーのレンダラー。
Python（Pillow + numpy）でフレームを生成し、ffmpeg で H.264 に書き出す。

## 出力

- `out/TWO_kinetic_1440x1080.mp4` — 4:3 / 24fps / 21.8s（マスター）
- `out/TWO_kinetic_960x720.mp4` — 参考動画と同じ解像度の軽量版
- `out/contact_sheet.png` — 1秒ごとのサムネイル

（mp4 は .gitignore 済み。`python3 render_two.py out/TWO_kinetic.mp4` で再生成できる）

## 構成（秒）

| 時間 | シーン |
|---|---|
| 0.0 – 0.55 | 赤いカードに巨大な「TWO」、破線ガイド、ピクセルグリッチ |
| 0.55 – 3.45 | 紙地。「TWO began with one question:」を単語ごとにタイプ、"question:" に手描きの下線 |
| 3.45 – 6.25 | 「what does it really mean to create?」、"create?" を手描きの丸で囲む |
| 6.25 – 9.65 | 黒地 + サーマル（熱画像）シルエット。「Not clothes for the sake of clothes.」 |
| 9.65 – 13.05 | 「but something intentional,」→「made with purpose.」黒から白へ転じ、シルエットが影に冷える |
| 13.05 – 16.45 | 紙地に T / W / O の文字が漂い、赤い走り書きの丸。「Each piece carries that search.」 |
| 16.45 – 19.85 | 黒地 + サーマル。「I hope it resonates with you too.」 |
| 19.85 – 21.8 | 紙地に巨大な「TWO」のアウトロ、"made with purpose." |

## MV 素材の差し替え

シルエットのシーン（3・4・6）はフッテージ用のスロットになっている。
`footage/` に `clipA.mp4` `clipB.mp4` `clipC.mp4` を置いて実行すると、
輝度でキーイングしたシルエットにサーマルのカラーマップが掛かる。

```
python3 render_two.py out/TWO_kinetic.mp4 --footage footage
# 被写体が背景より暗い素材のときは
python3 render_two.py out/TWO_kinetic.mp4 --footage footage --key-invert
```

素材が無いときは手続き的に描いた服（Tシャツ）のシルエットが使われる。

## 必要なもの

- Python 3 + Pillow + numpy
- ffmpeg
- Inter フォント（`/usr/share/fonts/opentype/inter/`）
