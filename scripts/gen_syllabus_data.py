"""生成 syllabus_*.json / weights.json / legacy_kp_map.json（一次性）。"""
from __future__ import annotations

import json
import os
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def dump(path: str, obj: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("wrote", path)


def main() -> None:
    os.makedirs(DATA, exist_ok=True)

    math_l1 = {
        "calc": {"name": "高等数学", "weight": 0.60},
        "linalg": {"name": "线性代数", "weight": 0.20},
        "prob": {"name": "概率论与数理统计", "weight": 0.20},
    }
    math_kps = [
        ("函数极限与连续", "calc", 0.055, "极限定义与计算、无穷小比较、间断点、闭区间连续性质",
         ["极限", "连续", "洛必达", "等价无穷小"]),
        ("一元微分学（求导与作图）", "calc", 0.070, "导数/微分、各类求导法则、单调极值凹凸渐近线、最值应用",
         ["导数", "求导", "极值", "凹凸", "作图"]),
        ("微分中值定理与泰勒", "calc", 0.045, "Rolle/Lagrange/Cauchy、Taylor公式、证明题",
         ["中值定理", "罗尔", "拉格朗日", "柯西", "泰勒"]),
        ("一元积分学（计算）", "calc", 0.065, "不定/定积分、换元分部、有理/三角/无理积分",
         ["不定积分", "定积分", "换元", "分部积分"]),
        ("变限积分与积分应用", "calc", 0.050, "积分上限函数、几何/物理应用、平均值",
         ["变限", "积分上限", "面积", "体积"]),
        ("反常积分", "calc", 0.020, "反常积分定义、比较判别法、计算",
         ["广义积分", "敛散性"]),
        ("向量代数与空间解析几何", "calc", 0.040, "向量运算、平面直线、曲面曲线、二次曲面",
         ["空间几何", "直线平面", "二次曲面", "空间解析几何"]),
        ("多元函数微分学", "calc", 0.060, "偏导/全微分、复合与隐函数、方向导数梯度、极值",
         ["偏导", "全微分", "梯度", "多元极值", "多元"]),
        ("二重积分与三重积分", "calc", 0.050, "重积分概念与计算（直角/极/柱/球）、简单应用",
         ["二重积分", "三重积分", "极坐标"]),
        ("曲线积分与格林公式", "calc", 0.055, "两类曲线积分、格林公式、路径无关",
         ["曲线积分", "格林"]),
        ("曲面积分与高斯斯托克斯", "calc", 0.050, "两类曲面积分、高斯/斯托克斯、散度旋度",
         ["曲面积分", "高斯公式", "斯托克斯", "散度", "旋度"]),
        ("常数项级数", "calc", 0.030, "敛散性判别、绝对/条件收敛",
         ["级数", "敛散性", "绝对收敛"]),
        ("幂级数与函数展开", "calc", 0.035, "收敛半径/域、和函数、泰勒展开",
         ["幂级数", "收敛半径", "泰勒展开"]),
        ("傅里叶级数", "calc", 0.010, "傅里叶系数、正余弦展开、狄利克雷定理",
         ["傅里叶"]),
        ("常微分方程", "calc", 0.050, "一阶各类、可降阶、二阶常系数线性与欧拉方程",
         ["微分方程", "ODE", "欧拉方程"]),
        ("行列式", "linalg", 0.025, "性质、按行（列）展开、计算技巧", ["行列式"]),
        ("矩阵与初等变换", "linalg", 0.040, "运算、逆矩阵、秩、初等变换、分块矩阵",
         ["矩阵", "初等变换", "逆矩阵", "线代", "线性代数"]),
        ("向量与线性相关性", "linalg", 0.045, "线性表示/相关、极大无关组、秩、等价向量组",
         ["线性相关", "极大无关组", "向量组"]),
        ("向量空间与正交化", "linalg", 0.020, "基、维数、坐标、过渡矩阵、Schmidt正交化",
         ["向量空间", "基", "过渡矩阵", "施密特"]),
        ("线性方程组", "linalg", 0.040, "Cramer、解的判定、基础解系、通解",
         ["方程组", "基础解系", "通解"]),
        ("特征值与特征向量", "linalg", 0.045, "特征值/向量、相似对角化、实对称矩阵",
         ["特征值", "特征向量", "对角化", "相似"]),
        ("二次型", "linalg", 0.025, "标准形/规范形、正交变换与配方法、正定性",
         ["二次型", "正定", "规范形"]),
        ("随机事件与概率", "prob", 0.035, "事件运算、古典/几何概型、公式、独立性",
         ["概率", "全概率", "贝叶斯", "古典概型"]),
        ("一维随机变量及分布", "prob", 0.040, "分布函数、离散/连续型、常见分布、变量函数分布",
         ["分布", "正态分布", "二项分布", "随机变量"]),
        ("多维随机变量及分布", "prob", 0.045, "联合/边缘/条件分布、独立性、二维常见分布",
         ["二维", "联合分布", "边缘分布", "条件分布"]),
        ("数字特征", "prob", 0.035, "期望、方差、协方差、相关系数、函数期望",
         ["期望", "方差", "协方差", "相关系数"]),
        ("大数定律与中心极限定理", "prob", 0.015, "Chebyshev不等式、大数定律、CLT应用",
         ["大数定律", "中心极限"]),
        ("数理统计基本概念", "prob", 0.030, "总体/样本、统计量、χ²/t/F分布、抽样分布",
         ["抽样分布", "卡方", "t分布", "F分布"]),
        ("参数估计", "prob", 0.040, "矩估计、MLE、无偏性/有效性、置信区间",
         ["矩估计", "最大似然", "置信区间"]),
        ("假设检验", "prob", 0.020, "两类错误、正态总体均值/方差检验",
         ["假设检验", "显著性"]),
    ]

    raw_sum: dict[str, float] = defaultdict(float)
    for _n, l1, w, _s, _a in math_kps:
        raw_sum[l1] += w
    math_kp_weights: dict[str, float] = {}
    math_kps_meta: dict[str, dict] = {}
    for name, l1, w, scope, aliases in math_kps:
        nw = round(w / raw_sum[l1] * math_l1[l1]["weight"], 4)
        math_kp_weights[name] = nw
        math_kps_meta[name] = {"l1": l1, "scope": scope, "aliases": aliases}
    total = sum(math_kp_weights.values())
    if abs(total - 1.0) > 1e-6:
        k = max(math_kp_weights, key=math_kp_weights.get)
        math_kp_weights[k] = round(math_kp_weights[k] + (1.0 - total), 4)

    syllabus_math = {
        "subject": "math",
        "syllabus": "考研数学一-2026",
        "l1": math_l1,
        "kps": math_kps_meta,
    }
    weights_math = {
        "syllabus": "考研数学一-2026",
        "l1_weights": {k: v["weight"] for k, v in math_l1.items()},
        "kp_weights": math_kp_weights,
        "exam_style": 0.7,
        "theory_extension": 0.3,
    }

    comm_l1 = {
        "sig_rand": {"name": "确定信号及随机信号分析", "weight": 1.15},
        "analog_mod": {"name": "模拟调制", "weight": 1.00},
        "baseband": {"name": "数字基带传输", "weight": 1.15},
        "passband": {"name": "数字频带传输", "weight": 1.25},
        "source": {"name": "信源及信源编码", "weight": 1.05},
        "channel": {"name": "信道及信道容量", "weight": 1.10},
        "coding": {"name": "信道编码", "weight": 1.15},
        "spread": {"name": "扩频及多载波通信", "weight": 0.95},
    }
    comm_kps = [
        ("确定信号与频谱分析", "sig_rand", 1.05, "傅里叶级数/变换、能量谱与功率谱、LTI系统",
         ["傅里叶", "频谱", "功率谱", "能量谱"]),
        ("带通信号与希尔伯特变换", "sig_rand", 1.00, "解析信号、带通信号/系统、无失真条件",
         ["希尔伯特", "解析信号", "带通"]),
        ("随机过程统计特性", "sig_rand", 1.10, "均值/方差/相关函数、平稳性、遍历性",
         ["随机过程", "自相关", "平稳", "遍历"]),
        ("高斯过程与窄带噪声", "sig_rand", 1.10, "高斯过程、窄带平稳高斯噪声、包络相位",
         ["高斯过程", "窄带噪声"]),
        ("AWGN与匹配滤波器", "sig_rand", 1.15, "高斯白噪声、通过滤波器、匹配滤波器输出SNR",
         ["白噪声", "匹配滤波器", "AWGN"]),
        ("模拟线性调制", "analog_mod", 1.00, "DSB-SC、AM、SSB原理/框图/频谱/解调",
         ["AM", "DSB", "SSB", "包络检波"]),
        ("模拟角度调制", "analog_mod", 1.05, "PM/FM关系、卡松公式、FM频谱与带宽",
         ["FM", "PM", "调频", "卡松公式"]),
        ("模拟调制抗噪声性能", "analog_mod", 1.10, "相干解调/包络检波/鉴频的输入输出SNR",
         ["信噪比", "抗噪声"]),
        ("载波同步与频分复用", "analog_mod", 0.95, "载波同步方法、FDM概念",
         ["载波同步", "FDM"]),
        ("数字基带波形与线路码型", "baseband", 1.05, "PAM波形、常用线路码、码型选择",
         ["线路码", "AMI", "HDB3", "PAM"]),
        ("基带信号功率谱密度", "baseband", 1.10, "随机序列PAM功率谱、主瓣带宽",
         ["基带功率谱"]),
        ("基带最佳接收", "baseband", 1.10, "AWGN下匹配滤波接收、抽样判决、误码率基础",
         ["最佳接收", "抽样判决"]),
        ("ISI与奈奎斯特准则", "baseband", 1.20, "码间干扰、无ISI条件、升余弦、最佳基带系统",
         ["ISI", "码间干扰", "奈奎斯特", "升余弦"]),
        ("眼图均衡与部分响应", "baseband", 1.00, "眼图判读、均衡、第I类部分响应",
         ["眼图", "均衡", "部分响应"]),
        ("二进制数字调制", "passband", 1.20, "OOK/2FSK/2PSK/DPSK原理、带宽与频带利用率",
         ["2PSK", "BPSK", "DPSK", "2FSK", "OOK", "误码率"]),
        ("QPSK与OQPSK", "passband", 1.15, "原理、功率谱、相干解调误比特率",
         ["QPSK", "OQPSK", "四相"]),
        ("信号空间与统计判决", "passband", 1.15, "矢量表示、最佳接收机、似然比/MAP",
         ["信号空间", "MAP", "似然比"]),
        ("M进制调制MASK/MPSK/MQAM", "passband", 1.20, "星座图、调制解调框图、功率谱、频带利用率",
         ["QAM", "16QAM", "星座图", "MPSK", "MASK"]),
        ("格雷映射与MFSK", "passband", 1.05, "格雷码映射、MFSK频谱与误符号率",
         ["格雷码", "MFSK"]),
        ("信息熵与互信息", "source", 1.05, "H(X)、I(X;Y)、熵/联合熵/条件熵",
         ["熵", "互信息", "信息论"]),
        ("采样与PCM量化编码", "source", 1.10, "低通/带通采样、均匀/非均匀量化、A律、时分复用",
         ["采样", "PCM", "量化", "A律"]),
        ("限失真信源编码概念", "source", 0.90, "率失真思想、无失真编码定理（概念级）",
         ["率失真", "信源编码定理"]),
        ("信道模型与衰落特性", "channel", 1.05, "无失真信道、衰落、相干带宽/时间、时延/多普勒",
         ["衰落", "多径", "相干带宽", "无线通信"]),
        ("信道容量", "channel", 1.15, "BSC容量、AWGN容量公式及应用",
         ["信道容量", "香农公式"]),
        ("线性分组码与汉明码", "coding", 1.15, "汉明距/重量、生成/监督矩阵、伴随式译码、汉明码",
         ["汉明码", "生成矩阵", "伴随式"]),
        ("循环码与CRC", "coding", 1.10, "生成多项式、系统码编码、CRC",
         ["循环码", "CRC"]),
        ("卷积码与维特比译码", "coding", 1.15, "状态图/格图、编码、Viterbi、交织",
         ["卷积码", "维特比", "格图", "交织"]),
        ("扩频与m序列", "spread", 1.00, "LFSR、m序列、直序扩频、正交码、CDMA",
         ["扩频", "m序列", "CDMA"]),
        ("扰码与Rake概念", "spread", 0.90, "扰码/解扰、多径分集Rake",
         ["扰码", "Rake"]),
        ("OFDM基本原理", "spread", 1.00, "OFDM思想、循环前缀、峰均比、子载波间干扰",
         ["OFDM", "循环前缀", "峰均比"]),
    ]
    comm_kp_weights: dict[str, float] = {}
    comm_kps_meta: dict[str, dict] = {}
    for name, l1, w, scope, aliases in comm_kps:
        comm_kp_weights[name] = w
        comm_kps_meta[name] = {"l1": l1, "scope": scope, "aliases": aliases}

    syllabus_comm = {
        "subject": "comm",
        "syllabus": "北邮801-通信原理-2026",
        "textbook": "周炯槃《通信原理》第4版 Ch2-11",
        "l1": comm_l1,
        "kps": comm_kps_meta,
    }
    weights_comm = {
        "syllabus": "北邮801-通信原理-2026",
        "l1_weights": {k: v["weight"] for k, v in comm_l1.items()},
        "kp_weights": comm_kp_weights,
        "exam_style": 0.6,
        "theory_extension": 0.4,
    }

    legacy = {
        "math": {
            "极限与连续": "函数极限与连续",
            "微分中值定理": "微分中值定理与泰勒",
            "一元函数积分": "一元积分学（计算）",
            "多元函数微分": "多元函数微分学",
            "二重积分与曲线积分": "曲线积分与格林公式",
            "无穷级数": "常数项级数",
            "常微分方程": "常微分方程",
            "线性代数": "矩阵与初等变换",
            "概率论与数理统计": "一维随机变量及分布",
            "空间解析几何": "向量代数与空间解析几何",
        },
        "comm": {
            "随机过程": "随机过程统计特性",
            "调制解调": "二进制数字调制",
            "信源编码": "采样与PCM量化编码",
            "信道编码": "卷积码与维特比译码",
            "信号与系统": "确定信号与频谱分析",
            "数字信号处理": "确定信号与频谱分析",
            "通信网络": "信道模型与衰落特性",
            "无线通信": "信道模型与衰落特性",
            "光通信": "信道模型与衰落特性",
            "信息论基础": "信息熵与互信息",
        },
    }

    dump(os.path.join(DATA, "syllabus_math.json"), syllabus_math)
    dump(os.path.join(DATA, "syllabus_comm.json"), syllabus_comm)
    dump(os.path.join(DATA, "legacy_kp_map.json"), legacy)
    dump(os.path.join(DATA, "weights.json"), {"math": weights_math, "comm": weights_comm})
    print("math kps", len(math_kp_weights), "sum", round(sum(math_kp_weights.values()), 4))
    print("comm kps", len(comm_kp_weights))


if __name__ == "__main__":
    main()
