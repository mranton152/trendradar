"""Пул терминов для замера скоринга в отрыве от генерации кандидатов.

Зачем отдельный пул: в доках записано, что скоринг работает, а узкое место —
генерация кандидатов. Проверить это утверждение можно, только зафиксировав
кандидатов вручную. Тогда всё, что останется, — качество ранжирования.

Фон нужен, чтобы перцентильные ранги и peer-нормировка считались на реалистичном
распределении, а не на двух десятках заранее отобранных крайностей.
"""

# Ровный технологический фон домена: ни эталон, ни антиэталон.
ФОН = [
    "attention mechanism", "knowledge distillation", "neural architecture search",
    "adversarial example", "model compression", "active learning",
    "curriculum learning", "meta learning", "multi-task learning",
    "reinforcement learning from human feedback", "speech recognition",
    "semantic segmentation", "object detection", "anomaly detection",
    "recommender system", "time series forecasting", "causal inference",
    "bayesian optimization", "gaussian process", "topic modeling",
    "sentiment analysis", "named entity recognition", "question answering",
    "image captioning", "pose estimation", "point cloud", "domain adaptation",
    "continual learning", "quantization aware training", "sparse attention",
]
