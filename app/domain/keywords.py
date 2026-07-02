"""
keywords.py

领域关键词配置（domain-neutral）。

说明：
这里不写复杂逻辑，只保存关键词。
真正的评分和过滤逻辑放在 filters.py 中。

1. 后续方便维护关键词；
2. 不影响主过滤逻辑；
3. 后续可以针对具体研究方向扩展。
"""

from __future__ import annotations


# ============================================================
# 1. 来源相关关键词 Source Keywords
# ============================================================

DOMAIN_SOURCE_KEYWORDS: list[str] = [
    # 通用食品词
    "food",
    "foods",
    "dietary",
    "diet",
    "nutrition",
    "nutritional",
    "edible",

    # 奶与乳制品
    "milk",
    "human milk",
    "breast milk",
    "infant formula",
    "dairy",
    "colostrum",

    # 植物与农产品
    "plant",
    "plants",
    "fruit",
    "fruits",
    "vegetable",
    "vegetables",
    "cereal",
    "cereals",
    "grain",
    "grains",
    "rice",
    "wheat",
    "maize",
    "corn",
    "soybean",
    "tea",
    "coffee",
    "wine",
    "grape",
    "apple",
    "citrus",

    # 发酵食品
    "fermented food",
    "fermentation",
    "yogurt",
    "cheese",
    "beer",
    "soy sauce",
]


# ============================================================
# 2. 成分类别关键词 Component Class Keywords
# ============================================================

DOMAIN_COMPONENT_KEYWORDS: list[str] = [
    # 通用化合物
    "compound",
    "compounds",
    "metabolite",
    "metabolites",
    "small molecule",
    "small molecules",
    "natural product",
    "natural products",
    "bioactive compound",
    "bioactive compounds",

    # 糖类 / HMO / 糖链
    "oligosaccharide",
    "oligosaccharides",
    "human milk oligosaccharide",
    "human milk oligosaccharides",
    "hmo",
    "hmos",
    "glycan",
    "glycans",
    "glycome",
    "glycomics",
    "carbohydrate",
    "carbohydrates",
    "saccharide",
    "saccharides",
    "fucosyllactose",
    "lacto-n-tetraose",
    "lacto-n-neotetraose",
    "sialyllactose",

    # 多酚 / 黄酮
    "polyphenol",
    "polyphenols",
    "flavonoid",
    "flavonoids",
    "phenolic compound",
    "phenolic compounds",
    "anthocyanin",
    "anthocyanins",
    "catechin",
    "quercetin",

    # 脂质
    "lipid",
    "lipids",
    "lipidomics",
    "fatty acid",
    "fatty acids",
    "phospholipid",
    "phospholipids",
    "triacylglycerol",
    "triglyceride",

    # 肽 / 蛋白水解产物
    "peptide",
    "peptides",
    "bioactive peptide",
    "bioactive peptides",

    # 其他常见成分
    "vitamin",
    "vitamins",
    "alkaloid",
    "alkaloids",
    "terpenoid",
    "terpenoids",
    "organic acid",
    "organic acids",
]


# ============================================================
# 3. 结构分析关键词 Structural Analysis Keywords
# ============================================================

STRUCTURE_ANALYSIS_KEYWORDS: list[str] = [
    "structure",
    "structural",
    "structural analysis",
    "structural characterization",
    "structural elucidation",
    "structure elucidation",
    "structure identification",
    "structure annotation",
    "molecular structure",
    "chemical structure",

    "identification",
    "characterization",
    "annotation",
    "dereplication",
    "putative identification",
    "tentative identification",

    "isomer",
    "isomers",
    "isomeric",
    "linkage",
    "linkages",
    "fragmentation",
    "fragmentation pattern",
    "fragment ion",
    "fragment ions",
    "diagnostic ion",
    "diagnostic ions",
]


# ============================================================
# 4. 质谱与分析方法关键词 Mass Spectrometry / Analytical Keywords
# ============================================================

MASS_SPEC_KEYWORDS: list[str] = [
    # 质谱通用
    "mass spectrometry",
    "mass spectrometric",
    "ms",
    "ms/ms",
    "msn",
    "tandem mass spectrometry",

    # LC-MS / GC-MS / MALDI
    "lc-ms",
    "lc-ms/ms",
    "uplc-ms",
    "uplc-ms/ms",
    "uhplc-ms",
    "uhplc-ms/ms",
    "hplc-ms",
    "hplc-ms/ms",
    "gc-ms",
    "gc-ms/ms",
    "maldi",
    "maldi-ms",
    "maldi-tof",
    "maldi-tof-ms",

    # 高分辨质谱
    "hrms",
    "high-resolution mass spectrometry",
    "orbitrap",
    "q-tof",
    "qtof",
    "tof-ms",

    # 离子与碎片
    "precursor ion",
    "product ion",
    "fragment ion",
    "neutral loss",
    "collision energy",
    "cid",
    "hcd",
    "adduct",
    "ion mode",
    "positive ion mode",
    "negative ion mode",

    # 色谱与保留时间
    "chromatography",
    "liquid chromatography",
    "gas chromatography",
    "retention time",
    "retention index",
]


# ============================================================
# 5. 组学方向关键词 Omics Keywords
# ============================================================

OMICS_KEYWORDS: list[str] = [
    "metabolomics",
    "metabolomic",
    "foodomics",
    "glycomics",
    "lipidomics",
    "nutrimetabolomics",
    "untargeted metabolomics",
    "targeted metabolomics",
    "metabolic profiling",
    "chemical profiling",
]


# ============================================================
# 6. 强相关关键词 Strong Positive Keywords
# ============================================================

# 命中这些词时，一般说明和本项目高度相关。
STRONG_POSITIVE_KEYWORDS: list[str] = [
    "human milk oligosaccharides",
    "human milk oligosaccharide",
    "hmo",
    "hmos",
    "lc-ms/ms",
    "structural elucidation",
    "structural characterization",
    "structure annotation",
    "fragmentation pattern",
    "diagnostic ions",
    "food metabolomics",
    "foodomics",
    "glycomics",
    "mass spectrometry-based metabolomics",
]


# ============================================================
# 7. 排除关键词 Exclusion Keywords
# ============================================================

# 这些词不是绝对无用，但 V0 阶段为了保持文献库干净，先过滤掉。
EXCLUSION_KEYWORDS: list[str] = [
    # 临床治疗方向
    "clinical trial",
    "randomized controlled trial",
    "patient survival",
    "tumor",
    "cancer therapy",
    "chemotherapy",
    "immunotherapy",

    # 药物递送 / 药代动力学方向
    "drug delivery",
    "pharmacokinetics",
    "pharmacodynamics",
    "drug metabolism",
    "therapeutic efficacy",

    # 基因表达方向
    "gene expression",
    "transcriptomics",
    "rna-seq",
    "genome-wide association",
    "gwas",
    "protein expression",

    # 动物疾病模型
    "mouse model",
    "mice model",
    "rat model",
    "animal disease model",

    # 明显偏医学诊断
    "biomarker for cancer",
    "disease diagnosis",
    "clinical biomarker",
]


# ============================================================
# 8. 方法章节优先关键词 Section Priority Keywords
# ============================================================

# 后续 RAG 检索时，可以优先检索这些章节。
METHOD_SECTION_KEYWORDS: list[str] = [
    "materials and methods",
    "methods",
    "experimental",
    "sample preparation",
    "lc-ms/ms analysis",
    "mass spectrometry",
    "data processing",
    "structure elucidation",
    "structural characterization",
]
