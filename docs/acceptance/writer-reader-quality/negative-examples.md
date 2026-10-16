# Fixed negative examples — SYNTHETIC_TEST_ONLY

These are hand-written evaluation mutations, not Writer generations, baselines,
real company findings, or runtime instructions. Use the comparison case's fixed
material. A fragment can test a failure mode but cannot substitute for the
complete introduction/middle/ending comparison.

## Exaggerated effect

> このチェックリストで全チームの処理時間が改善した。Aは8分から6分へ短縮し、Bも同じ効果が期待できる。直ちに全社へ展開すれば、業務の遅れを解消できる。

Expected distinction: semantic failure. B actually rises from 4 to 5 min/case;
causality, uniform benefit and elimination of delay are unsupported. Interest in
this claim cannot compensate for the missing adverse observation.

## Accurate list without movement

> 調査は前後各1週間、各チーム・各期間20件の完了案件を対象とした。Aの平均処理時間は8分から6分、Bは4分から5分だった。案件構成と同時期の変更は測定・統制していない。因果効果は確定できない。
>
> 前後各1週間の平均値を比較した。Aは8分から6分、Bは4分から5分だった。案件構成と同時期の変更は未測定・未統制である。因果効果は確定できない。

Expected distinction: the facts remain intact, but the second paragraph adds no
recognition or next question. This is an editorial weakness, not evidence of
false numbers or a reason to reject draft storage.

## Entry alone, stagnant middle

> 同じチェックリストを広げるか。Aでは時間が下がり、Bでは上がった。この違いを残して判断する必要がある。
>
> Aは8分から6分、Bは4分から5分だった。次節では結果を述べる。
>
> 結果はAが8分から6分、Bが4分から5分である。次節では考察を述べる。

Expected distinction: a relevant opening does not establish middle-section
momentum. A complete assessment must also retain the method and causal limits;
their absence here is separately a fidelity/completeness concern.

## Ending misses the decision

> 今後は一般的な教育とガバナンスを強化すべきである。

Expected distinction: this adds a recommendation not supplied in the case and
does not answer the initial rollout decision. It fails meaning as well as
payoff. Do not count this as an accurate but merely boring ending. A truthful
yet weak ending would retain the supplied deferral, B investigation and follow-up
while failing to explain their relation to the initial question.
