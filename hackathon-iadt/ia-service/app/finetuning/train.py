"""
Script de treino QLoRA — executa FORA do Docker, em máquina com GPU.

Recomendado: Google Colab Pro (A100), RunPod, Lambda Labs ou qualquer GPU com ≥ 16GB VRAM.

Dependências (instalar via finetuning-requirements.txt):
    pip install -r finetuning-requirements.txt

Uso:
    # 1. Gerar dados
    python -m app.finetuning.data_generator --samples 50 --output ./data/raw_pairs.jsonl

    # 2. Formatar
    python -m app.finetuning.data_formatter --input ./data/raw_pairs.jsonl --output ./data

    # 3. Treinar
    python -m app.finetuning.train

    # 4. (Opcional) Enviar para HuggingFace Hub
    python -m app.finetuning.train --push-to-hub --hub-model-id "seu-usuario/report-lora"
"""

import argparse
import json
import sys
from pathlib import Path


def _check_dependencies():
    missing = []
    for pkg in ["torch", "transformers", "peft", "trl", "datasets", "bitsandbytes"]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(
            f"ERRO: Dependências de GPU não instaladas: {missing}\n"
            "Execute: pip install -r finetuning-requirements.txt",
            file=sys.stderr,
        )
        sys.exit(1)


def train(
    base_model_id: str = "mistralai/Mistral-7B-Instruct-v0.3",
    train_file: str = "./data/train.jsonl",
    val_file: str = "./data/val.jsonl",
    output_dir: str = "./output/report-lora-adapter",
    hub_model_id: str = "",
    push_to_hub: bool = False,
    num_epochs: int = 3,
    batch_size: int = 4,
    grad_accum: int = 4,
    learning_rate: float = 2e-4,
    max_seq_length: int = 4096,
):
    """Executa o fine-tuning QLoRA completo."""
    _check_dependencies()

    import torch
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from trl import SFTTrainer

    print(f"GPU disponível: {torch.cuda.is_available()}")
    if not torch.cuda.is_available():
        print("AVISO: Sem GPU detectada. O treino será extremamente lento.", file=sys.stderr)

    # ── Quantização 4-bit (QLoRA) ──────────────────────────────────
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.float16,
        bnb_4bit_use_double_quant=True,
    )

    # ── Carregar modelo base ────────────────────────────────────────
    print(f"Carregando modelo base: {base_model_id}")
    model = AutoModelForCausalLM.from_pretrained(
        base_model_id,
        quantization_config=bnb_config,
        device_map="auto",
        trust_remote_code=True,
    )
    model = prepare_model_for_kbit_training(model)

    tokenizer = AutoTokenizer.from_pretrained(base_model_id, trust_remote_code=True)
    tokenizer.pad_token = tokenizer.eos_token
    tokenizer.padding_side = "right"

    # ── LoRA ────────────────────────────────────────────────────────
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        bias="none",
        task_type="CAUSAL_LM",
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
    )
    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # ── Dataset ─────────────────────────────────────────────────────
    for path in [train_file, val_file]:
        if not Path(path).exists():
            raise FileNotFoundError(
                f"Arquivo não encontrado: {path}\n"
                "Execute data_generator.py e data_formatter.py primeiro."
            )

    dataset = load_dataset(
        "json",
        data_files={"train": train_file, "validation": val_file},
    )
    print(f"Dataset: {len(dataset['train'])} treino, {len(dataset['validation'])} val")

    # ── Argumentos de treino ─────────────────────────────────────────
    training_args = TrainingArguments(
        output_dir=output_dir,
        num_train_epochs=num_epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size,
        gradient_accumulation_steps=grad_accum,
        learning_rate=learning_rate,
        warmup_ratio=0.05,
        lr_scheduler_type="cosine",
        optim="paged_adamw_8bit",
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        logging_steps=10,
        report_to="none",
        push_to_hub=push_to_hub,
        hub_model_id=hub_model_id if push_to_hub else None,
        fp16=True,
        dataloader_pin_memory=False,
    )

    # ── SFTTrainer ──────────────────────────────────────────────────
    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset["train"],
        eval_dataset=dataset["validation"],
        args=training_args,
        max_seq_length=max_seq_length,
    )

    print("Iniciando treino...")
    trainer.train()

    # ── Salvar adapter ───────────────────────────────────────────────
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)
    print(f"✅ Adapter salvo em: {output_dir}")

    # Salvar metadados do treino
    meta = {
        "base_model_id": base_model_id,
        "num_epochs": num_epochs,
        "train_samples": len(dataset["train"]),
        "val_samples": len(dataset["validation"]),
        "lora_r": 16,
        "lora_alpha": 32,
        "max_seq_length": max_seq_length,
    }
    with open(Path(output_dir) / "training_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    if push_to_hub and hub_model_id:
        model.push_to_hub(hub_model_id)
        tokenizer.push_to_hub(hub_model_id)
        print(f"✅ Adapter publicado no Hub: {hub_model_id}")

    return output_dir


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fine-tuning QLoRA para geração de relatórios")
    parser.add_argument("--model",          default="mistralai/Mistral-7B-Instruct-v0.3")
    parser.add_argument("--train-file",     default="./data/train.jsonl")
    parser.add_argument("--val-file",       default="./data/val.jsonl")
    parser.add_argument("--output-dir",     default="./output/report-lora-adapter")
    parser.add_argument("--hub-model-id",   default="")
    parser.add_argument("--push-to-hub",    action="store_true")
    parser.add_argument("--epochs",         type=int,   default=3)
    parser.add_argument("--batch-size",     type=int,   default=4)
    parser.add_argument("--grad-accum",     type=int,   default=4)
    parser.add_argument("--lr",             type=float, default=2e-4)
    parser.add_argument("--max-seq-length", type=int,   default=4096)
    args = parser.parse_args()

    train(
        base_model_id=args.model,
        train_file=args.train_file,
        val_file=args.val_file,
        output_dir=args.output_dir,
        hub_model_id=args.hub_model_id,
        push_to_hub=args.push_to_hub,
        num_epochs=args.epochs,
        batch_size=args.batch_size,
        grad_accum=args.grad_accum,
        learning_rate=args.lr,
        max_seq_length=args.max_seq_length,
    )
