# -*- coding: utf-8 -*-
"""
科学指标（一键计算）
====================
把海洋/气象时序分析里最常用的一批指标做成统一接口：给它一条 `TimeSeries`，
返回结构化的结果（数值表 + 可叠加的曲线 + 图上标注文字），
界面和命令行都能直接用。

指标分四组：

* **基本统计**  均值/标准差/极值/变异系数
* **趋势与检验** 线性趋势（含 95% 置信区间与 p 值）、Mann-Kendall 非参数检验、
                Sen's slope（稳健斜率）
* **周期与相关** 季节循环、去季节、功率谱（FFT）、自相关
* **变率与极值** 变率与有效自由度、极值/超阈值频率、逐月距平

术语约定（图与表里都用这套，避免歧义）：
  * 趋势一律折算成 **每年** 的变化量，单位写作 `<单位>/年`
  * 显著性用 p 值，p<0.05 标 ★，p<0.01 标 ★★，p<0.001 标 ★★★
  * 区域平均默认已做 cos(纬度) 面积加权（见 series.py）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

from .series import TimeSeries

try:
    from scipy import stats as _st
except Exception:                                       # noqa: BLE001
    _st = None


# ----------------------------------------------------------------------
@dataclass
class IndicatorResult:
    """一个指标的计算结果。"""

    key: str
    title: str
    kind: str = "table"                 # table / line / bars / spectrum
    x: Optional[np.ndarray] = None
    y: Optional[np.ndarray] = None
    xlabel: str = ""
    ylabel: str = ""
    label: str = ""                     # 图例名
    annotation: str = ""                # 叠在图上的一小段文字
    table: List[Tuple[str, str]] = field(default_factory=list)
    overlay: bool = False               # True = 叠加在原序列上，不单独占一张图
    note: str = ""                      # 方法说明 / 注意事项


#: 分组目录：组名 → [(键, 中文名, 一句话说明)]
INDICATOR_CATALOG: Dict[str, List[Tuple[str, str, str]]] = {
    "基本统计": [
        ("summary", "统计摘要", "样本数、均值、标准差、极值、变异系数"),
        ("anomaly", "距平序列", "每个时次减去总体均值"),
        ("cum_anomaly", "累积距平", "距平的累积和，看阶段性转折"),
        ("running", "滑动平均", "平滑掉高频扰动，突出低频变化"),
    ],
    "趋势与检验": [
        ("trend", "线性趋势", "最小二乘拟合，给出斜率、95% 置信区间与 p 值"),
        ("mk", "Mann-Kendall 检验", "非参数趋势检验，不要求正态分布"),
        ("sen", "Sen's 斜率", "斜率的中位数估计，抗离群值"),
    ],
    "周期与相关": [
        ("seasonal", "季节循环", "逐月气候态（多年同月平均）"),
        ("deseasonal", "去季节", "逐月减去气候态，得到季节内信号"),
        ("spectrum", "功率谱", "FFT 功率谱，看周期能量分布"),
        ("autocorr", "自相关", "滞后相关，判断记忆性与有效自由度"),
    ],
    "变率与极值": [
        ("variability", "变率与有效自由度", "去季节后的标准差与有效自由度"),
        ("monthly_anomaly", "逐月距平", "按月距平，看年际与季节内波动"),
        ("extreme", "极值/超阈值", "按分位数阈值统计超阈频率"),
    ],
}

ALL_INDICATORS: List[str] = [k for g in INDICATOR_CATALOG.values()
                             for k, _n, _d in g]


def stars(p: float) -> str:
    if p is None or not np.isfinite(p):
        return ""
    if p < 0.001:
        return " ★★★"
    if p < 0.01:
        return " ★★"
    if p < 0.05:
        return " ★"
    return ""


def _fmt(v: float, nd: int = 4) -> str:
    if v is None or not np.isfinite(v):
        return "—"
    a = abs(v)
    if a != 0 and (a < 1e-3 or a >= 1e6):
        return "%.3e" % v
    return ("%%.%df" % nd) % v


def _clean(ts: TimeSeries) -> TimeSeries:
    return ts.clean()


# ----------------------------------------------------------------------
# 统计工具
# ----------------------------------------------------------------------
def ols_trend(t: np.ndarray, y: np.ndarray):
    """最小二乘线性回归，返回 (斜率, 截距, p值, 半宽95%CI, R²)。"""
    n = y.size
    if n < 3:
        return np.nan, np.nan, np.nan, np.nan, np.nan
    A = np.vstack([t, np.ones(n)]).T
    try:
        slope, inter = np.linalg.lstsq(A, y, rcond=None)[0]
    except Exception:                                   # noqa: BLE001
        return np.nan, np.nan, np.nan, np.nan, np.nan
    fit = slope * t + inter
    resid = y - fit
    dof = n - 2
    sxx = float(np.sum((t - t.mean()) ** 2))
    if sxx <= 0 or dof <= 0:
        return float(slope), float(inter), np.nan, np.nan, np.nan
    s2 = float(np.sum(resid ** 2) / dof)
    se = np.sqrt(s2 / sxx) if s2 > 0 else 0.0
    if se > 0 and _st is not None:
        tstat = slope / se
        p = float(2 * _st.t.sf(abs(tstat), dof))
        half = float(_st.t.ppf(0.975, dof) * se)
    else:
        p, half = np.nan, np.nan
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    r2 = 1.0 - float(np.sum(resid ** 2)) / ss_tot if ss_tot > 0 else np.nan
    return float(slope), float(inter), p, half, r2


def mann_kendall(y: np.ndarray):
    """
    Mann-Kendall 趋势检验（含连续性校正）。
    返回 (S, Z, p, tau, 趋势方向文字)。
    """
    n = y.size
    if n < 4:
        return np.nan, np.nan, np.nan, np.nan, "样本太少"
    s = 0
    for k in range(n - 1):
        s += int(np.sign(y[k + 1:] - y[k]).sum())
    # 结（ties）修正
    _, counts = np.unique(y, return_counts=True)
    tie = float(np.sum(counts * (counts - 1) * (2 * counts + 5)))
    var = (n * (n - 1) * (2 * n + 5) - tie) / 18.0
    if var <= 0:
        return float(s), 0.0, 1.0, 0.0, "无明显趋势"
    if s > 0:
        z = (s - 1) / np.sqrt(var)
    elif s < 0:
        z = (s + 1) / np.sqrt(var)
    else:
        z = 0.0
    p = float(2 * _norm_sf(abs(z)))
    tau = s / (0.5 * n * (n - 1))
    if p < 0.05:
        direction = "显著上升" if z > 0 else "显著下降"
    else:
        direction = "无显著趋势"
    return float(s), float(z), p, float(tau), direction


def _norm_sf(x: float) -> float:
    if _st is not None:
        return float(_st.norm.sf(x))
    return float(0.5 * np.erfc(x / np.sqrt(2)))


def sen_slope(t: np.ndarray, y: np.ndarray):
    """Sen's slope：所有点对斜率的中位数，抗离群值。返回 (斜率, 下界, 上界)。"""
    n = y.size
    if n < 3:
        return np.nan, np.nan, np.nan
    slopes = []
    for i in range(n - 1):
        dt = t[i + 1:] - t[i]
        m = dt != 0
        if np.any(m):
            slopes.append((y[i + 1:][m] - y[i]) / dt[m])
    if not slopes:
        return np.nan, np.nan, np.nan
    alls = np.concatenate(slopes)
    med = float(np.median(alls))
    # 中位数的置信区间（非参数，基于秩序统计量）
    m = alls.size
    try:
        zc = 1.96
        var = (n * (n - 1) * (2 * n + 5)) / 18.0
        nlo = int(np.floor((m - zc * np.sqrt(var)) / 2))
        nhi = int(np.ceil((m + zc * np.sqrt(var)) / 2)) + 1
        srt = np.sort(alls)
        lo = float(srt[max(0, min(nlo, m - 1))])
        hi = float(srt[max(0, min(nhi, m - 1))])
    except Exception:                                   # noqa: BLE001
        lo = hi = med
    return med, lo, hi


def seasonal_cycle(ts: TimeSeries):
    """返回 (12 个月的均值, 每个月样本数)。没数据的位置是 NaN。"""
    months = ts.time.astype("datetime64[M]").astype(int) % 12 + 1
    vals = ts.values
    means = np.full(12, np.nan)
    ns = np.zeros(12, dtype=int)
    for m in range(1, 13):
        sel = vals[months == m]
        ns[m - 1] = sel.size
        if sel.size:
            means[m - 1] = float(np.mean(sel))
    return means, ns


def seasonal_strength(ts: TimeSeries) -> float:
    """
    季节信号强度（0~1）：按月分组的组间方差占总方差的比例。

    用来判断「先做趋势拟合前要不要先去季节」。实测：一条叠加了 3℃ 季节振幅的
    序列，若直接拟合趋势，斜率会被带偏 50% 以上 —— 因为三年样本里季节项的
    相位与时间项并不严格正交。
    """
    clim, ns = seasonal_cycle(ts)
    good = ~np.isnan(clim)
    if good.sum() < 2 or ts.values.size < 8:
        return 0.0
    months = ts.time.astype("datetime64[M]").astype(int) % 12 + 1
    tot = float(np.var(ts.values))
    if tot <= 0:
        return 0.0
    between = float(np.nansum(ns[good] * (clim[good] - np.mean(ts.values)) ** 2)
                    / max(1, int(ns[good].sum())))
    return max(0.0, min(1.0, between / tot))


def deseasonalize(ts: TimeSeries) -> TimeSeries:
    """逐月减去该月气候态。样本不足的月份按总体均值处理。"""
    clim, ns = seasonal_cycle(ts)
    overall = float(np.mean(ts.values))
    clim = np.where(np.isnan(clim), overall, clim)
    months = ts.time.astype("datetime64[M]").astype(int) % 12 + 1
    out = ts.values - clim[months - 1]
    return TimeSeries(time=ts.time, values=out, label=ts.label,
                      units=ts.units, long_name=ts.long_name,
                      variable=ts.variable, stat=ts.stat, region=ts.region,
                      time_source=ts.time_source, meta=dict(ts.meta))


def acf(y: np.ndarray, max_lag: int):
    y = y - y.mean()
    denom = float(np.sum(y * y))
    if denom <= 0:
        return np.zeros(max_lag + 1)
    n = y.size
    return np.array([float(np.sum(y[:n - k] * y[k:]) / denom)
                     for k in range(min(max_lag, n - 1) + 1)])


# ----------------------------------------------------------------------
# 各指标实现
# ----------------------------------------------------------------------
def _summary(ts: TimeSeries, **kw) -> IndicatorResult:
    s = ts.stats()
    if not s.get("n"):
        return IndicatorResult("summary", "统计摘要", note="没有有效样本")
    mean, std = s["mean"], s["std"]
    cv = std / abs(mean) if mean else np.nan
    rng = s["max"] - s["min"]
    rows = [
        ("样本数", "%d" % s["n"]),
        ("时间跨度", "%s ~ %s" % (_iso(ts.time.min()), _iso(ts.time.max()))),
        ("均值", "%s %s" % (_fmt(mean), ts.units)),
        ("标准差", "%s %s" % (_fmt(std), ts.units)),
        ("变异系数", _fmt(cv)),
        ("中位数", "%s %s" % (_fmt(s["median"]), ts.units)),
        ("最小值", "%s %s" % (_fmt(s["min"]), ts.units)),
        ("最大值", "%s %s" % (_fmt(s["max"]), ts.units)),
        ("极差", "%s %s" % (_fmt(rng), ts.units)),
    ]
    return IndicatorResult("summary", "统计摘要", kind="table", table=rows)


def _iso(d) -> str:
    try:
        return str(np.datetime_as_string(np.datetime64(d), unit="D"))
    except Exception:                                   # noqa: BLE001
        return str(d)


def _trend(ts: TimeSeries, deseasonal="auto", **kw) -> IndicatorResult:
    """
    线性趋势。

    ★ 默认先去季节再拟合 ★
    这看着像个细节，实测影响极大：造一条真值 +0.80 ℃/年、季节振幅 3 ℃ 的
    36 个月序列，**直接拟合会得到 1.25 ℃/年（偏高 57%）** —— 因为样本里
    季节项的相位与时间项并不严格正交，季节信号会"偷走"一部分趋势。
    去季节后回到 0.85 附近。
    """
    ts = _clean(ts)
    strength = seasonal_strength(ts)
    do_ds = (deseasonal is True) or \
            (deseasonal == "auto" and strength >= 0.15 and ts.values.size >= 8)
    work = deseasonalize(ts) if do_ds else ts

    t = work.t_years()
    y = work.values
    slope, inter, p, half, r2 = ols_trend(t, y)

    # 拟合线画回原始序列上：把截距挪到原序列均值处，
    # 这样直线正好穿过季节振荡的中轴，不会因为去季节而整体偏移。
    t_all = ts.t_years()
    if np.isfinite(slope):
        c = float(np.mean(ts.values)) - slope * float(np.mean(t_all))
        fit = slope * t_all + c
    else:
        fit = np.full_like(t_all, np.nan)

    rows = [
        ("变化率", "%s %s/年" % (_fmt(slope), ts.units)),
        ("每十年", "%s %s/10年%s" % (_fmt(slope * 10), ts.units, stars(p))),
        ("95% 置信区间", "± %s %s/年" % (_fmt(half), ts.units)),
        ("p 值", _fmt(p)),
        ("R²", _fmt(r2)),
        ("显著性", "显著" if (np.isfinite(p) and p < 0.05) else "不显著"),
        ("季节信号强度", "%.2f" % strength),
        ("是否去季节", "是（默认）" if do_ds else "否"),
    ]
    ann = "趋势 %s %s/年%s" % (_fmt(slope), ts.units, stars(p))
    if np.isfinite(r2):
        ann += "   R²=%s" % _fmt(r2, 3)
    if do_ds:
        ann += "（已去季节）"
    note = "最小二乘线性回归；★ p<0.05，★★ p<0.01，★★★ p<0.001"
    if do_ds:
        note += ("\n季节信号较强（强度 %.2f），已先逐月去气候态再拟合，"
                 "否则趋势会被季节循环带偏" % strength)
    else:
        note += "\n季节信号不强（强度 %.2f），按原序列拟合" % strength
    return IndicatorResult(
        "trend", "线性趋势", kind="line", overlay=True,
        x=ts.time, y=fit, label="线性趋势", annotation=ann, table=rows,
        note=note)



def _mk(ts: TimeSeries, deseasonal="auto", **kw) -> IndicatorResult:
    """
    Mann-Kendall 非参数趋势检验。

    与 trend / sen 一样**默认先去季节**：季节振幅往往远大于年际趋势
    （实测造一条 +0.8 ℃/年、季节振幅 3 ℃ 的序列，不做去季节时
    MK 会因为季节相位来回抵消而判定"无显著趋势"，把真趋势漏掉）。
    """
    ts = _clean(ts)
    strength = seasonal_strength(ts)
    do_ds = (deseasonal is True) or             (deseasonal == "auto" and strength >= 0.15 and ts.values.size >= 8)
    work = deseasonalize(ts) if do_ds else ts
    s, z, p, tau, direction = mann_kendall(work.values)
    rows = [
        ("趋势判定", direction + stars(p)),
        ("统计量 S", _fmt(s, 1)),
        ("标准化 Z", _fmt(z, 3)),
        ("p 值", _fmt(p)),
        ("Kendall τ", _fmt(tau, 3)),
        ("是否去季节", "是（默认）" if do_ds else "否"),
    ]
    return IndicatorResult(
        "mk", "Mann-Kendall 趋势检验", kind="table", table=rows,
        annotation="MK: %s%s" % (direction, stars(p)),
        note="非参数检验，不要求数据服从正态分布；"
             "适合有离群值或明显偏态的序列（如 SST 极值、叶绿素）")


def _sen(ts: TimeSeries, deseasonal="auto", **kw) -> IndicatorResult:
    """
    Sen's slope。与 trend 一样默认先去季节，保证两个指标口径一致 ——
    否则「Sen 给量值、MK 判显著性」这套标准组合会因为一个去季节、
    一个没去而互相矛盾。
    """
    ts = _clean(ts)
    strength = seasonal_strength(ts)
    do_ds = (deseasonal is True) or \
            (deseasonal == "auto" and strength >= 0.15 and ts.values.size >= 8)
    work = deseasonalize(ts) if do_ds else ts
    med, lo, hi = sen_slope(work.t_years(), work.values)

    rows = [
        ("Sen's 斜率", "%s %s/年" % (_fmt(med), ts.units)),
        ("每十年", "%s %s/10年" % (_fmt(med * 10), ts.units)),
        ("95% 置信区间", "[%s, %s] %s/年" % (_fmt(lo), _fmt(hi), ts.units)),
        ("是否去季节", "是（默认）" if do_ds else "否"),
    ]
    ann = "Sen 斜率 %s %s/年" % (_fmt(med), ts.units)
    note = ("取所有点对斜率的中位数，抗离群值；与 MK 检验常配对使用"
            "（MK 判显著性、Sen 给量值）")
    if do_ds:
        note += "\n季节信号较强，已先去季节，与「线性趋势」口径一致"
    return IndicatorResult(
        "sen", "Sen's 斜率", kind="table", table=rows,
        annotation=ann, note=note)



def _anomaly(ts: TimeSeries, **kw) -> IndicatorResult:
    ts = _clean(ts)
    m = float(np.mean(ts.values))
    anom = ts.values - m
    return IndicatorResult(
        "anomaly", "距平序列", kind="bars", overlay=False,
        x=ts.time, y=anom, ylabel="距平 [%s]" % ts.units, label="距平",
        table=[("基准（总平均）", "%s %s" % (_fmt(m), ts.units)),
               ("最大正距平", "%s" % _fmt(float(np.max(anom)))),
               ("最大负距平", "%s" % _fmt(float(np.min(anom))))],
        annotation="距平基准 %s %s" % (_fmt(m), ts.units))


def _cum_anomaly(ts: TimeSeries, **kw) -> IndicatorResult:
    ts = _clean(ts)
    anom = ts.values - float(np.mean(ts.values))
    cum = np.cumsum(anom)
    return IndicatorResult(
        "cum_anomaly", "累积距平", kind="line", x=ts.time, y=cum,
        ylabel="累积距平 [%s·次]" % ts.units, label="累积距平",
        note="曲线由升转降（或反之）的位置提示序列出现阶段性转折")


def _running(ts: TimeSeries, window: int = 0, **kw) -> IndicatorResult:
    ts = _clean(ts)
    n = ts.values.size
    if window <= 0:
        window = max(3, min(n // 10 or 3, 31))
    window = int(min(window, max(2, n)))
    y = ts.values
    kern = np.ones(window) / window
    smooth = np.convolve(y, kern, mode="same")
    # 两端用较短的窗，避免边界被拉向 0
    half = window // 2
    for i in range(min(half, n)):
        w = i + half + 1
        smooth[i] = np.mean(y[:min(w, n)])
        j = n - 1 - i
        smooth[j] = np.mean(y[max(0, j - half):])
    return IndicatorResult(
        "running", "滑动平均", kind="line", overlay=True,
        x=ts.time, y=smooth, label="%d 点滑动平均" % window,
        annotation="滑动窗口 %d 点" % window,
        table=[("窗口长度", "%d" % window)])


def _seasonal(ts: TimeSeries, **kw) -> IndicatorResult:
    ts = _clean(ts)
    months = ts.time.astype("datetime64[M]").astype(int) % 12 + 1
    vals = ts.values
    means, ns = [], []
    for m in range(1, 13):
        sel = vals[months == m]
        means.append(float(np.mean(sel)) if sel.size else np.nan)
        ns.append(int(sel.size))
    means = np.array(means)
    if np.all(np.isnan(means)):
        return IndicatorResult("seasonal", "季节循环", note="无法按月分组")
    amp = float(np.nanmax(means) - np.nanmin(means))
    peak = int(np.nanargmax(means)) + 1
    rows = [("第 %d 月均值" % (i + 1), "%s (%d)" % (_fmt(means[i]), ns[i]))
            for i in range(12)]
    return IndicatorResult(
        "seasonal", "季节循环", kind="bars",
        x=np.arange(1, 13), y=means,
        xlabel="月份", ylabel="气候态 [%s]" % ts.units, label="逐月气候态",
        table=[("振幅（最高-最低）", "%s %s" % (_fmt(amp), ts.units)),
               ("峰值月份", "%d 月" % peak)] + rows,
        annotation="季节振幅 %s %s，峰值 %d 月" % (_fmt(amp), ts.units, peak),
        note="多年同月平均（气候态）；样本不足的月份标记为 —")


def _deseasonal(ts: TimeSeries, **kw) -> IndicatorResult:
    ts = _clean(ts)
    months = ts.time.astype("datetime64[M]").astype(int) % 12 + 1
    vals = ts.values
    clim = np.full(12, np.nan)
    for m in range(1, 13):
        sel = vals[months == m]
        if sel.size:
            clim[m - 1] = float(np.mean(sel))
    good = ~np.isnan(clim)
    if not good.any():
        return IndicatorResult("deseasonal", "去季节", note="无法按月分组")
    out = vals - clim[months - 1]
    std = float(np.nanstd(out, ddof=1)) if np.isfinite(out).sum() > 1 else np.nan
    return IndicatorResult(
        "deseasonal", "去季节序列", kind="line", x=ts.time, y=out,
        ylabel="距平 [%s]" % ts.units, label="去季节",
        table=[("去季节后标准差", "%s %s" % (_fmt(std), ts.units))],
        annotation="去季节后标准差 %s %s" % (_fmt(std), ts.units),
        note="逐月减去该月的多年平均，得到季节内/年际信号")


def _spectrum(ts: TimeSeries, **kw) -> IndicatorResult:
    ts = _clean(ts)
    t = ts.t_days()
    y = ts.values
    n = y.size
    if n < 8:
        return IndicatorResult("spectrum", "功率谱", note="样本太少（<8），无法做谱分析")
    dt = float(np.median(np.diff(t))) or 1.0
    uniform = bool(np.allclose(np.diff(t), dt, rtol=0.25, atol=dt * 0.25))
    w = np.hanning(n)
    yw = (y - y.mean()) * w
    Y = np.fft.rfft(yw)
    freq = np.fft.rfftfreq(n, d=dt)                 # 周期/单位时间
    power = (np.abs(Y) ** 2) * 2.0 / (n * float(np.mean(w ** 2)))
    keep = freq > 0
    freq, power = freq[keep], power[keep]
    period = 1.0 / freq
    # 峰值周期
    pk = int(np.argmax(power)) if power.size else 0
    peak_period = float(period[pk]) if power.size else np.nan
    note = "FFT 功率谱（Hann 窗，扣除均值）；横轴为周期，单位与采样间隔一致"
    if not uniform:
        note += "；⚠ 采样间隔不均匀，谱形仅供参考"
    if np.isfinite(peak_period):
        if peak_period >= 320:
            ann = "主周期 ≈ %.0f 天（≈%.1f 年）" % (peak_period, peak_period / 365.2425)
        elif peak_period >= 27:
            ann = "主周期 ≈ %.0f 天（≈%.1f 个月）" % (peak_period, peak_period / 30.4375)
        else:
            ann = "主周期 ≈ %.1f 天" % peak_period
    else:
        ann = ""
    rows = [("采样间隔", "%.2f 天" % dt),
            ("Nyquist 周期", "%.2f 天" % (2 * dt)),
            ("最长可分辨周期", "%.1f 天" % float(period.max()) if period.size else "—")]
    if np.isfinite(peak_period):
        rows.insert(0, ("峰值周期", ann.replace("主周期 ", "")))
    return IndicatorResult(
        "spectrum", "功率谱", kind="spectrum", x=period, y=power,
        xlabel="周期（天）", ylabel="功率", label="功率谱",
        annotation=ann, table=rows, note=note)



def _autocorr(ts: TimeSeries, max_lag: int = 0, **kw) -> IndicatorResult:
    ts = _clean(ts)
    n = ts.values.size
    if n < 5:
        return IndicatorResult("autocorr", "自相关", note="样本太少")
    if max_lag <= 0:
        max_lag = min(60, max(5, n // 4))
    a = acf(ts.values, max_lag)
    idx = np.arange(a.size)
    # 一阶自相关的 95% 白噪声阈值
    thr = 1.96 / np.sqrt(n)
    lag1 = float(a[1]) if a.size > 1 else np.nan
    decorr = next((int(i) for i in idx if abs(a[i]) < thr), None)
    return IndicatorResult(
        "autocorr", "自相关函数", kind="bars", x=idx, y=a,
        xlabel="滞后（采样点）", ylabel="自相关系数", label="ACF",
        annotation="1 阶自相关 %.3f" % lag1 if np.isfinite(lag1) else "",
        table=[("1 阶自相关", _fmt(lag1, 3)),
               ("白噪声 95% 阈值", "± %s" % _fmt(thr, 3)),
               ("去相关时间", "%d 点" % decorr if decorr is not None else "> 最大滞后")],
        note="自相关越强说明序列记忆性越强，独立样本数远少于总样本数")


def _variability(ts: TimeSeries, **kw) -> IndicatorResult:
    ts = _clean(ts)
    y = ts.values
    n = y.size
    sd = float(np.std(y, ddof=1)) if n > 1 else np.nan
    months = ts.time.astype("datetime64[M]").astype(int) % 12 + 1
    clim = np.array([np.mean(y[months == m]) if np.any(months == m) else np.nan
                     for m in range(1, 13)])
    ds = y - clim[months - 1]
    sd_ds = float(np.nanstd(ds, ddof=1)) if np.isfinite(ds).sum() > 1 else np.nan
    a1 = acf(y, 1)[1] if n > 2 else 0.0
    # 有效自由度（一阶自相关近似）
    neff = n * (1 - a1) / (1 + a1) if abs(1 + a1) > 0 else float(n)
    return IndicatorResult(
        "variability", "变率与有效自由度", kind="table",
        table=[
            ("总标准差", "%s %s" % (_fmt(sd), ts.units)),
            ("去季节标准差", "%s %s" % (_fmt(sd_ds), ts.units)),
            ("样本数", "%d" % n),
            ("有效自由度", "%.1f（名义 %d）" % (neff, n)),
            ("1 阶自相关", _fmt(a1, 3)),
        ],
        note="序列存在自相关时，独立样本数少于总样本数；"
             "做显著性检验应使用有效自由度，否则容易过度显著")


def _monthly_anomaly(ts: TimeSeries, **kw) -> IndicatorResult:
    ts = _clean(ts)
    key = ts.time.astype("datetime64[M]")
    uniq = np.unique(key)
    vals = np.array([float(np.mean(ts.values[key == k])) for k in uniq])
    clim = np.array([np.mean(vals[uniq.astype("datetime64[M]").astype(int) % 12
                                  == (k.astype(int) % 12)])
                     for k in uniq.astype(int) % 12] if uniq.size else [])
    anom = vals - clim if clim.size == vals.size else vals - np.mean(vals)
    return IndicatorResult(
        "monthly_anomaly", "逐月距平", kind="bars",
        x=uniq.astype("datetime64[s]"), y=anom,
        ylabel="距平 [%s]" % ts.units, label="逐月距平",
        annotation="逐月距平（相对各月气候态）",
        table=[("月数", "%d" % uniq.size),
               ("最大正距平", _fmt(float(np.max(anom)))),
               ("最大负距平", _fmt(float(np.min(anom))))],
        note="先把数据按月平均，再减去各月的气候态")


def _extreme(ts: TimeSeries, q: float = 90.0, **kw) -> IndicatorResult:
    ts = _clean(ts)
    y = ts.values
    thr_hi = float(np.percentile(y, q))
    thr_lo = float(np.percentile(y, 100 - q))
    n_hi = int(np.sum(y > thr_hi))
    n_lo = int(np.sum(y < thr_lo))
    n = y.size
    years = ts.time.astype("datetime64[Y]").astype(int) + 1970
    uy = np.unique(years)
    per_year = [(int(yr), int(np.sum(y[years == yr] > thr_hi))) for yr in uy]
    return IndicatorResult(
        "extreme", "极值 / 超阈值统计", kind="bars",
        x=np.array([p[0] for p in per_year], dtype="float64"),
        y=np.array([p[1] for p in per_year], dtype="float64"),
        xlabel="年份", ylabel="超阈次数", label="超阈次数",
        annotation="阈值 %.4g（P%.0f）" % (thr_hi, q),
        table=[("高阈值 P%.0f" % q, "%s %s" % (_fmt(thr_hi), ts.units)),
               ("低阈值 P%.0f" % (100 - q), "%s %s" % (_fmt(thr_lo), ts.units)),
               ("超上阈次数", "%d / %d（%.1f%%）" % (n_hi, n, 100.0 * n_hi / n)),
               ("超下阈次数", "%d / %d（%.1f%%）" % (n_lo, n, 100.0 * n_lo / n)),
               ("最大值", "%s %s" % (_fmt(float(np.max(y))), ts.units)),
               ("最小值", "%s %s" % (_fmt(float(np.min(y))), ts.units))],
        note="阈值取样本分位数。逐年统计超阈次数可以看极端事件是否变频繁")


# ----------------------------------------------------------------------
_REGISTRY: Dict[str, Callable[..., IndicatorResult]] = {
    "summary": _summary,
    "trend": _trend,
    "mk": _mk,
    "sen": _sen,
    "anomaly": _anomaly,
    "cum_anomaly": _cum_anomaly,
    "running": _running,
    "seasonal": _seasonal,
    "deseasonal": _deseasonal,
    "spectrum": _spectrum,
    "autocorr": _autocorr,
    "variability": _variability,
    "monthly_anomaly": _monthly_anomaly,
    "extreme": _extreme,
}


def compute(key: str, ts: TimeSeries, **kw) -> IndicatorResult:
    fn = _REGISTRY.get(key)
    if fn is None:
        raise KeyError("没有这个指标：%s（可用：%s）"
                       % (key, ", ".join(ALL_INDICATORS)))
    return fn(ts, **kw)


def compute_many(keys: Sequence[str], ts: TimeSeries, **kw
                 ) -> List[IndicatorResult]:
    out = []
    for k in keys:
        try:
            out.append(compute(k, ts, **kw))
        except Exception as exc:                        # noqa: BLE001
            out.append(IndicatorResult(k, k, kind="table",
                                       table=[("计算出错", str(exc))]))
    return out


def indicator_title(key: str) -> str:
    for group in INDICATOR_CATALOG.values():
        for k, name, _d in group:
            if k == key:
                return name
    return key


def indicator_hint(key: str) -> str:
    for group in INDICATOR_CATALOG.values():
        for k, _n, desc in group:
            if k == key:
                return desc
    return ""
