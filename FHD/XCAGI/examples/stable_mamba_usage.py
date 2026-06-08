"""
Neuro-DDD 2.0 - 稳定 Mamba 层快速使用指南

本指南展示如何使用优化后的稳定 Mamba 层进行长序列处理
"""

import sys
from pathlib import Path
import numpy as np

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.neuro_domains.stable_mamba import StableMambaLayer, AdaptiveMambaLayer


def demo_basic_usage():
    """基础使用示例"""
    print("="*80)
    print("基础使用示例")
    print("="*80)
    
    # 1. 创建稳定 Mamba 层
    print("\n1. 创建稳定 Mamba 层")
    layer = StableMambaLayer(
        d_model=768,      # 隐藏层维度
        d_state=16,       # 状态维度
        d_conv=4,         # 卷积核大小
        use_layer_norm=True,  # 使用层归一化
        use_dropout=False     # 不使用 dropout（推理时）
    )
    print(f"   ✅ 创建成功：d_model=768, d_state=16")
    
    # 2. 准备输入数据
    print("\n2. 准备输入数据")
    batch_size = 2
    seq_len = 512
    d_model = 768
    x = np.random.randn(batch_size, seq_len, d_model).astype(np.float32)
    print(f"   输入形状：{x.shape}")
    
    # 3. 执行前向传播
    print("\n3. 执行前向传播")
    output, stats = layer.forward(x, training=False)
    print(f"   输出形状：{output.shape}")
    print(f"   稳定性：{'✅ 稳定' if stats['is_stable'] else '⚠️ 不稳定'}")
    print(f"   最大状态范数：{stats['max_state_norm']:.2f}")
    
    # 4. 检查数值健康
    print("\n4. 数值健康检查")
    has_nan = np.any(np.isnan(output))
    has_inf = np.any(np.isinf(output))
    print(f"   NaN 检查：{'❌ 发现 NaN' if has_nan else '✅ 无 NaN'}")
    print(f"   Inf 检查：{'❌ 发现 Inf' if has_inf else '✅ 无 Inf'}")
    
    print()


def demo_long_sequence():
    """长序列处理示例"""
    print("="*80)
    print("长序列处理示例（10K+ tokens）")
    print("="*80)
    
    layer = StableMambaLayer(d_model=768, d_state=16)
    
    # 测试不同长度
    sequence_lengths = [512, 2048, 8192, 10240]
    
    print("\n序列长度测试:")
    for seq_len in sequence_lengths:
        x = np.random.randn(1, seq_len, 768).astype(np.float32)
        output, stats = layer.forward(x)
        
        status = "✅ 稳定" if stats['is_stable'] else "⚠️ 不稳定"
        print(f"   {seq_len:5d} tokens - {status} - "
              f"最大范数：{stats['max_state_norm']:.2f}")
    
    print()


def demo_adaptive_layer():
    """自适应多头 Mamba 示例"""
    print("="*80)
    print("自适应多头 Mamba 示例")
    print("="*80)
    
    # 创建自适应层
    layer = AdaptiveMambaLayer(
        d_model=768,
        d_state=16,
        num_heads=4  # 4 个头
    )
    print(f"   ✅ 创建成功：4 头，每头维度={768//4}")
    
    # 前向传播
    x = np.random.randn(2, 512, 768).astype(np.float32)
    output, stats = layer.forward(x)
    
    print(f"   输出形状：{output.shape}")
    print(f"   头数：{len(stats['heads'])}")
    
    for head_stat in stats['heads']:
        print(f"   头 {head_stat['head']}: 最大范数={head_stat['max_norm']:.2f}")
    
    print()


def demo_training_mode():
    """训练模式示例"""
    print("="*80)
    print("训练模式示例（带 Dropout）")
    print("="*80)
    
    # 创建带 dropout 的层
    layer = StableMambaLayer(
        d_model=768,
        d_state=16,
        use_dropout=True,
        dropout_rate=0.1
    )
    
    x = np.random.randn(2, 256, 768).astype(np.float32)
    
    # 训练模式
    output_train, _ = layer.forward(x, training=True)
    print(f"   训练模式输出形状：{output_train.shape}")
    
    # 评估模式
    output_eval, _ = layer.forward(x, training=False)
    print(f"   评估模式输出形状：{output_eval.shape}")
    
    # 验证 dropout 效果
    is_different = not np.array_equal(output_train, output_eval)
    print(f"   Dropout 生效：{'✅' if is_different else '❌'}")
    
    print()


def demo_numerical_stability():
    """数值稳定性演示"""
    print("="*80)
    print("数值稳定性演示")
    print("="*80)
    
    layer = StableMambaLayer(d_model=768, d_state=16)
    
    # 极端输入测试
    test_cases = [
        ("正常输入", np.random.randn(1, 512, 768).astype(np.float32)),
        ("大值输入", np.random.randn(1, 512, 768).astype(np.float32) * 100),
        ("小值输入", np.random.randn(1, 512, 768).astype(np.float32) * 0.001),
    ]
    
    print("\n极端输入测试:")
    for name, x in test_cases:
        output, stats = layer.forward(x)
        
        has_nan = np.any(np.isnan(output))
        has_inf = np.any(np.isinf(output))
        is_stable = stats['is_stable']
        
        status = "✅" if (not has_nan and not has_inf and is_stable) else "❌"
        print(f"   {name:10} - {status} - 稳定：{is_stable}")
    
    print()


def demo_performance_comparison():
    """性能对比演示"""
    print("="*80)
    print("性能对比演示")
    print("="*80)
    
    import time
    
    layer = StableMambaLayer(d_model=768, d_state=16)
    
    # 不同长度的性能测试
    test_configs = [
        ("短序列", 128),
        ("中等序列", 512),
        ("长序列", 2048),
        ("超长序列", 8192)
    ]
    
    print("\n延迟测试（平均 10 次）:")
    for name, seq_len in test_configs:
        x = np.random.randn(1, seq_len, 768).astype(np.float32)
        
        times = []
        for _ in range(10):
            start = time.perf_counter()
            layer.forward(x)
            times.append((time.perf_counter() - start) * 1000)
        
        avg_time = sum(times) / len(times)
        print(f"   {name:10} ({seq_len:5d} tokens): {avg_time:8.2f} ms")
    
    print()


def demo_integration_with_service():
    """与深度学习服务集成"""
    print("="*80)
    print("与深度学习服务集成")
    print("="*80)
    
    from app.neuro_domains.deep_learning_service import (
        ModelConfig, ModelType, MambaBERTHybrid, ModelInput
    )
    
    # 创建配置
    config = ModelConfig(
        model_type=ModelType.MAMBA_BERT_HYBRID,
        hidden_size=768,
        num_layers=12,
        hybrid_ratio=0.5
    )
    
    # 创建混合模型
    model = MambaBERTHybrid(config)
    
    # 创建输入
    input_data = ModelInput(text="你好，请帮我查询订单状态")
    
    # 推理
    output = model.forward(input_data)
    
    print(f"   模型类型：Mamba-BERT 混合")
    print(f"   输入文本：{input_data.text}")
    print(f"   置信度：{output.confidence:.2f}")
    print(f"   处理时间：{output.processing_time_ms:.2f} ms")
    
    print()


def main():
    """运行所有演示"""
    print("\n" + "="*80)
    print("Neuro-DDD 2.0 - 稳定 Mamba 层使用指南")
    print("="*80)
    print()
    
    # 运行演示
    demo_basic_usage()
    demo_long_sequence()
    demo_adaptive_layer()
    demo_training_mode()
    demo_numerical_stability()
    demo_performance_comparison()
    demo_integration_with_service()
    
    print("="*80)
    print("演示完成！")
    print("="*80)
    print()
    print("下一步:")
    print("  1. 参考 stable_mamba.py 了解实现细节")
    print("  2. 查看 test_stable_mamba.py 了解测试用例")
    print("  3. 集成到您的项目中使用")
    print()


if __name__ == "__main__":
    main()
