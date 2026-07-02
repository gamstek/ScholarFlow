import re


def clean_text(text: str) -> str:
    """
    清洗文本。

    主要处理：
    1. 中文网页中的特殊空格
    2. 多余空格
    3. 多余换行
    4. 空行

    参数:
        text:
            原始文本。

    返回:
        清洗后的文本。
    """

    # 替换常见特殊空白字符
    text = text.replace("\xa0", " ")
    text = text.replace("\u3000", " ")

    # 多个空格压缩为一个空格
    text = re.sub(r"[ \t]+", " ", text)

    # 多个换行压缩
    text = re.sub(r"\n{3,}", "\n\n", text)

    # 去掉每行首尾空格
    lines = [line.strip() for line in text.splitlines()]

    # 删除空行
    cleaned_lines = [line for line in lines if line]

    return "\n".join(cleaned_lines)