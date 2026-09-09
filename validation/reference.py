"""Эталон: технологии, про которые задним числом известно, что они выстрелили.

Список собран ДО прогонов детектора и не меняется по их результатам.
Подгонять эталон под выдачу — то же самое, что подсматривать ответ: цифра
Precision@15 после такого ничего не значит, а жюри такое считывает мгновенно.

Срез 2021 выбран потому, что даёт пять лет на проверку и захватывает момент
до взрыва больших языковых моделей.
"""

ЭТАЛОН_ИИ_2021 = [
    "transformer", "vision transformer", "diffusion model",
    "self-supervised learning", "contrastive learning", "foundation model",
    "large language model", "prompt engineering", "retrieval augmented generation",
    "mixture of experts", "state space model", "neural radiance field",
    "graph neural network", "physics-informed neural network",
    "vision-language model", "low-rank adaptation", "vector database",
    "neural operator", "differentiable rendering",
]

# Заведомо НЕ зарождающиеся в 2021: к тому моменту это уже мейнстрим.
# Если они в топе — метод ловит популярность, а не слабый сигнал.
АНТИЭТАЛОН_ИИ_2021 = [
    "convolutional neural network", "recurrent neural network", "random forest",
    "support vector machine", "deep learning", "machine learning",
    "transfer learning", "internet of things", "big data", "cloud computing",
    "covid-19 pandemic", "image classification",
]
