"""
Configurações de hiperparâmetros para o fine-tuning QLoRA.
Separado do config principal (pydantic-settings) pois este módulo
roda como script standalone em GPU, fora do Docker.
"""

from dataclasses import dataclass, field


@dataclass
class LoRAConfig:
    r: int = 16                          # rank da decomposição LoRA
    lora_alpha: int = 32                 # escala (alpha/r = fator de aprendizado)
    lora_dropout: float = 0.05
    bias: str = "none"
    task_type: str = "CAUSAL_LM"
    # Camadas alvo — padrão para modelos decoder-only (Mistral, LLaMA, Phi, Qwen)
    target_modules: list = field(default_factory=lambda: [
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ])


@dataclass
class QuantizationConfig:
    load_in_4bit: bool = True
    bnb_4bit_compute_dtype: str = "float16"    # "bfloat16" se GPU suportar
    bnb_4bit_quant_type: str = "nf4"           # NormalFloat4 — melhor para QLoRA
    bnb_4bit_use_double_quant: bool = True      # quantização dupla economiza ~0.4 bits/param


@dataclass
class TrainingConfig:
    # Modelo base — troque pelo modelo escolhido pelo time
    base_model_id: str = "mistralai/Mistral-7B-Instruct-v0.3"

    # Saída
    output_dir: str = "./output/report-lora-adapter"
    hub_model_id: str = ""                     # ex: "seu-usuario/report-lora" (HuggingFace Hub)
    push_to_hub: bool = False

    # Dados
    train_file: str = "./data/train.jsonl"
    val_file: str = "./data/val.jsonl"
    max_seq_length: int = 4096

    # Treino
    num_train_epochs: int = 3
    per_device_train_batch_size: int = 4
    gradient_accumulation_steps: int = 4       # batch efetivo = 4 × 4 = 16
    learning_rate: float = 2e-4
    warmup_ratio: float = 0.05
    lr_scheduler_type: str = "cosine"
    optim: str = "paged_adamw_8bit"            # otimizador eficiente para QLoRA

    # Avaliação e salvamento
    eval_strategy: str = "epoch"
    save_strategy: str = "epoch"
    load_best_model_at_end: bool = True
    metric_for_best_model: str = "eval_loss"

    # Logging
    logging_steps: int = 10
    report_to: str = "none"                    # "wandb" se quiser tracking


@dataclass
class DataGenerationConfig:
    num_synthetic_samples: int = 50
    architecture_templates: list = field(default_factory=lambda: [
        "microservices_api_gateway",
        "monolith_single_db",
        "event_driven_kafka",
        "serverless_lambda_dynamodb",
        "kubernetes_service_mesh",
        "cqrs_event_sourcing",
        "bff_mobile_web",
        "data_pipeline_etl",
        "hexagonal_clean_arch",
        "multi_region_failover",
    ])
    variations_per_template: int = 5           # total: 10 templates × 5 = 50 pares
    train_split: float = 0.9                   # 90% treino, 10% validação
    output_dir: str = "./data"
