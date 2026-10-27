# functional_tests/test_01_preprocessing.py

import os
from powergrid_pipeline_v2.src.services.preprocessing_service import PreprocessingService

def run_test():
    print("--- 运行预处理服务功能测试 ---")
    service = PreprocessingService()
    
    # 定义输入输出路径
    dat_input = "powergrid_pipeline_v2/data/base_models/yunnan_base.dat"
    json_output_full = "runs/test_output/preprocessing/full_grid.json"
    json_output_500kv = "runs/test_output/preprocessing/grid_500kv.json"
    context_output = "runs/test_output/preprocessing/generated_context.json"
    
    # --- 测试1: dat_to_json (不筛选) ---
    print("\n[1/3] 测试 dat_to_json (不筛选)...")
    success, msg = service.dat_to_json(dat_input, json_output_full)
    assert success, f"dat_to_json(不筛选)失败: {msg}"
    assert os.path.exists(json_output_full)
    print("✅ 测试通过")

    # --- 测试2: dat_to_json (筛选500kV) ---
    print("\n[2/3] 测试 dat_to_json (筛选500kV)...")
    success, msg = service.dat_to_json(dat_input, json_output_500kv, filter_kv=500.0)
    assert success, f"dat_to_json(筛选500kV)失败: {msg}"
    assert os.path.exists(json_output_500kv)
    print("✅ 测试通过")

    # --- 测试3: build_context ---
    print("\n[3/3] 测试 build_context...")
    # 假设这些源文件已准备好
    success, msg = service.build_context(
        output_path=context_output,
        grid_structure_json_path=json_output_500kv, # 使用上一步的产出
        access_points_txt_path="data/source_texts/access_points.txt", # 假设你创建了这个文件
        node_coords_txt_path="data/source_texts/node_coordinates.txt", # 假设你创建了这个文件
        reference_doc_path="data/source_texts/Reference_solution.docx", # 假设你创建了这个文件
        task_description="现在将越州节点作为指定位置的节点，将越州节点加入到电网中，请生成五个可行的方案。" #固定任务内容
    )
    assert success, f"build_context失败: {msg}"
    assert os.path.exists(context_output)
    print("✅ 测试通过")

    print("\n--- 所有预处理服务测试完成 ---")

if __name__ == "__main__":
    # 准备: 确保源文件存在
    
    run_test()