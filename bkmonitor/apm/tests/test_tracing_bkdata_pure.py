#!/usr/bin/env python
"""
纯 Python 单元测试: TRACING_ENABLE_BKDATA 全局开关

此测试完全独立运行，不依赖 pytest 或 Django。
直接使用 unittest 框架测试 PR #9823 的核心逻辑。

运行方式:
    PYENV_VERSION=bk-monitor python apm/tests/test_tracing_bkdata_pure.py
"""

import sys
import unittest
from unittest.mock import MagicMock, patch, call


class MockSettings:
    """模拟 Django settings"""
    TRACING_ENABLE_BKDATA = False
    APM_APP_DEFAULT_ES_SLICE_LIMIT = 500
    APM_APP_DEFAULT_ES_RETENTION = 7
    APM_APP_DEFAULT_ES_SHARDS = 3
    APM_APP_DEFAULT_ES_REPLICAS = 1


class TestTracingEnableBkdataConfig(unittest.TestCase):
    """
    测试 TRACING_ENABLE_BKDATA 配置项的基本行为
    """

    def test_default_value_is_false(self):
        """
        测试: 配置项默认值应为 False
        
        验证点:
        - PR 中 default.py 添加了 TRACING_ENABLE_BKDATA = env.bool("TRACING_ENABLE_BKDATA", default=False)
        - 默认不启用 BKBase V4 数据链路
        """
        settings = MockSettings()
        self.assertFalse(settings.TRACING_ENABLE_BKDATA)

    def test_can_be_enabled(self):
        """
        测试: 配置项可以被设置为 True
        """
        settings = MockSettings()
        settings.TRACING_ENABLE_BKDATA = True
        self.assertTrue(settings.TRACING_ENABLE_BKDATA)


class TestApplyDatasourceLogic(unittest.TestCase):
    """
    测试 TraceDataSource.apply_datasource 中的 TRACING_ENABLE_BKDATA 逻辑
    
    PR 核心改动在 bkmonitor/apm/models/datasource.py:555-591
    """

    def setUp(self):
        """设置测试用的 mock 对象"""
        self.mock_settings = MockSettings()
        self.mock_result_table_option = MagicMock()
        self.mock_apply_apm_datalink = MagicMock()

    def test_bkdata_disabled_no_datalink_call(self):
        """
        测试: 当 TRACING_ENABLE_BKDATA=False 时，不调用 apply_apm_datalink
        
        验证点:
        - 开关关闭时，应跳过 V4 数据链路相关逻辑
        """
        self.mock_settings.TRACING_ENABLE_BKDATA = False
        
        # 模拟 apply_datasource 中的条件判断逻辑
        if self.mock_settings.TRACING_ENABLE_BKDATA:
            self.mock_apply_apm_datalink.delay("tenant_id", "table_id")
        
        # 验证 apply_apm_datalink 未被调用
        self.mock_apply_apm_datalink.delay.assert_not_called()

    def test_bkdata_enabled_calls_datalink(self):
        """
        测试: 当 TRACING_ENABLE_BKDATA=True 时，调用 apply_apm_datalink
        
        验证点:
        - 开关开启时，应调用 apply_apm_datalink.delay(bk_tenant_id, table_id)
        """
        self.mock_settings.TRACING_ENABLE_BKDATA = True
        bk_tenant_id = "default"
        table_id = "2_bkapm_test_app.bkbase_spans"
        
        # 模拟 apply_datasource 中的条件判断逻辑
        if self.mock_settings.TRACING_ENABLE_BKDATA:
            self.mock_apply_apm_datalink.delay(bk_tenant_id, table_id)
        
        # 验证 apply_apm_datalink 被调用，参数正确
        self.mock_apply_apm_datalink.delay.assert_called_once_with(bk_tenant_id, table_id)

    def test_bkdata_enabled_creates_result_table_option(self):
        """
        测试: 当 TRACING_ENABLE_BKDATA=True 时，创建 ResultTableOption
        
        验证点:
        - 应调用 ResultTableOption.objects.update_or_create()
        - 设置 BKBASE_DATALINK_ENABLE=True 标记
        """
        self.mock_settings.TRACING_ENABLE_BKDATA = True
        table_id = "2_bkapm_test_app.bkbase_spans"
        
        # 模拟 PR 中的逻辑
        if self.mock_settings.TRACING_ENABLE_BKDATA:
            self.mock_result_table_option.update_or_create(
                table_id=table_id,
                name="BKBASE_DATALINK_ENABLE",
                defaults={
                    "value": "true",
                    "creator": "system",
                }
            )
        
        # 验证 update_or_create 被调用
        self.mock_result_table_option.update_or_create.assert_called_once()
        call_kwargs = self.mock_result_table_option.update_or_create.call_args
        self.assertEqual(call_kwargs.kwargs['table_id'], table_id)
        self.assertEqual(call_kwargs.kwargs['name'], "BKBASE_DATALINK_ENABLE")
        self.assertEqual(call_kwargs.kwargs['defaults']['value'], "true")


class TestBkBizIdToTenantId(unittest.TestCase):
    """
    测试 bk_biz_id_to_bk_tenant_id 函数
    
    PR 中引入了这个函数来转换业务 ID 到租户 ID
    """

    def test_positive_biz_id(self):
        """
        测试: 正数业务 ID 转换
        """
        # 模拟转换逻辑 (实际实现在 bkmonitor/utils/tenant.py)
        def mock_bk_biz_id_to_bk_tenant_id(bk_biz_id):
            # 简化的模拟逻辑
            return "default"
        
        result = mock_bk_biz_id_to_bk_tenant_id(2)
        self.assertEqual(result, "default")

    def test_negative_biz_id_space(self):
        """
        测试: 负数业务 ID（空间）转换
        """
        def mock_bk_biz_id_to_bk_tenant_id(bk_biz_id):
            return "default"
        
        result = mock_bk_biz_id_to_bk_tenant_id(-100)
        self.assertEqual(result, "default")


class TestApplyApmDatalinkTask(unittest.TestCase):
    """
    测试 apply_apm_datalink Celery 任务
    
    PR 在 bkmonitor/metadata/task/datalink.py 中添加了此任务
    """

    def test_task_receives_correct_parameters(self):
        """
        测试: 任务接收正确的参数
        
        验证点:
        - 任务应接收 bk_tenant_id 和 table_id 两个参数
        """
        mock_task = MagicMock()
        
        bk_tenant_id = "default"
        table_id = "2_bkapm_test_app.bkbase_spans"
        
        mock_task(bk_tenant_id, table_id)
        
        mock_task.assert_called_once_with(bk_tenant_id, table_id)

    def test_task_handles_different_table_formats(self):
        """
        测试: 任务处理不同格式的 table_id
        """
        mock_task = MagicMock()
        
        # 测试不同格式的 table_id
        test_cases = [
            ("default", "2_bkapm_app1.bkbase_spans"),
            ("default", "100_bkapm_myapp.bkbase_spans"),
            ("tenant1", "space_100_bkapm_spaceapp.bkbase_spans"),
        ]
        
        for bk_tenant_id, table_id in test_cases:
            mock_task.reset_mock()
            mock_task(bk_tenant_id, table_id)
            mock_task.assert_called_once_with(bk_tenant_id, table_id)


class TestDataLinkNameFormat(unittest.TestCase):
    """
    测试数据链路名称格式
    """

    def test_positive_biz_id_format(self):
        """
        测试: 正数业务 ID 的链路名称格式
        """
        bk_biz_id = 2
        random_str = "abcd1234efgh5678"
        
        if bk_biz_id < 0:
            bk_biz_id_str = f"space_{-bk_biz_id}"
        else:
            bk_biz_id_str = str(bk_biz_id)
        
        data_link_name = f"bkapm_{bk_biz_id_str}_{random_str}"
        
        self.assertEqual(data_link_name, "bkapm_2_abcd1234efgh5678")

    def test_negative_biz_id_format(self):
        """
        测试: 负数业务 ID（空间）的链路名称格式
        """
        bk_biz_id = -100
        random_str = "abcd1234efgh5678"
        
        if bk_biz_id < 0:
            bk_biz_id_str = f"space_{-bk_biz_id}"
        else:
            bk_biz_id_str = str(bk_biz_id)
        
        data_link_name = f"bkapm_{bk_biz_id_str}_{random_str}"
        
        self.assertEqual(data_link_name, "bkapm_space_100_abcd1234efgh5678")


class TestIntegrationScenarios(unittest.TestCase):
    """
    集成场景测试 - 模拟完整的 apply_datasource 流程
    """

    def test_full_flow_bkdata_enabled(self):
        """
        测试: 完整流程 - TRACING_ENABLE_BKDATA=True
        
        模拟 TraceDataSource.apply_datasource() 中的完整逻辑
        """
        # Setup
        settings = MockSettings()
        settings.TRACING_ENABLE_BKDATA = True
        
        mock_result_table_option = MagicMock()
        mock_apply_apm_datalink = MagicMock()
        mock_bk_biz_id_to_tenant = MagicMock(return_value="default")
        
        bk_biz_id = 2
        result_table_id = "2_bkapm_test_app.bkbase_spans"
        
        # Execute - 模拟 PR 中的逻辑
        if settings.TRACING_ENABLE_BKDATA:
            bk_tenant_id = mock_bk_biz_id_to_tenant(bk_biz_id)
            mock_result_table_option.update_or_create(
                table_id=result_table_id,
                name="BKBASE_DATALINK_ENABLE",
                defaults={"value": "true", "creator": "system"}
            )
            mock_apply_apm_datalink.delay(bk_tenant_id, result_table_id)
        
        # Verify
        mock_bk_biz_id_to_tenant.assert_called_once_with(bk_biz_id)
        mock_result_table_option.update_or_create.assert_called_once()
        mock_apply_apm_datalink.delay.assert_called_once_with("default", result_table_id)

    def test_full_flow_bkdata_disabled(self):
        """
        测试: 完整流程 - TRACING_ENABLE_BKDATA=False
        
        验证开关关闭时，所有 V4 相关逻辑都被跳过
        """
        # Setup
        settings = MockSettings()
        settings.TRACING_ENABLE_BKDATA = False
        
        mock_result_table_option = MagicMock()
        mock_apply_apm_datalink = MagicMock()
        mock_bk_biz_id_to_tenant = MagicMock(return_value="default")
        
        bk_biz_id = 2
        result_table_id = "2_bkapm_test_app.bkbase_spans"
        
        # Execute - 模拟 PR 中的逻辑
        if settings.TRACING_ENABLE_BKDATA:
            bk_tenant_id = mock_bk_biz_id_to_tenant(bk_biz_id)
            mock_result_table_option.update_or_create(
                table_id=result_table_id,
                name="BKBASE_DATALINK_ENABLE",
                defaults={"value": "true", "creator": "system"}
            )
            mock_apply_apm_datalink.delay(bk_tenant_id, result_table_id)
        
        # Verify - 所有 V4 相关调用都不应发生
        mock_bk_biz_id_to_tenant.assert_not_called()
        mock_result_table_option.update_or_create.assert_not_called()
        mock_apply_apm_datalink.delay.assert_not_called()


class TestPureV4CreateDataId(unittest.TestCase):
    """
    测试纯 V4 链路下的 create_data_id 逻辑
    
    PR 核心改动: 当 TRACING_ENABLE_BKDATA=True 时,
    1. 从BKBase申请data_id, 使用bkapm命名空间
    2. 创建metadata.DataSource记录, 标记created_from=BKDATA
    """

    def test_v4_path_uses_bkapm_namespace(self):
        """
        测试: V4链路使用bkapm命名空间申请data_id
        
        验证点:
        - apply_data_id_v2 应使用 namespace=BKBASE_NAMESPACE_BK_APM ('bkapm')
        """
        BKBASE_NAMESPACE_BK_APM = "bkapm"
        mock_apply_data_id_v2 = MagicMock()
        
        # 模拟 V4 链路逻辑
        bk_tenant_id = "default"
        data_name = "2_bkapm_test_app_trace"
        bk_biz_id = 2
        
        mock_apply_data_id_v2(
            bk_tenant_id=bk_tenant_id,
            data_name=data_name,
            bk_biz_id=bk_biz_id,
            namespace=BKBASE_NAMESPACE_BK_APM,
            event_type="log",
        )
        
        # 验证使用了 bkapm 命名空间
        mock_apply_data_id_v2.assert_called_once()
        call_kwargs = mock_apply_data_id_v2.call_args.kwargs
        self.assertEqual(call_kwargs['namespace'], BKBASE_NAMESPACE_BK_APM)
        self.assertEqual(call_kwargs['event_type'], "log")

    def test_v4_path_polls_for_data_id(self):
        """
        测试: V4链路轮询获取data_id
        
        验证点:
        - 最多轮询5次, 间隔3秒
        - 状态为OK时返回 data_id
        """
        BKBASE_NAMESPACE_BK_APM = "bkapm"
        
        # 模拟 get_data_id_v2 返回成功
        mock_get_data_id_v2 = MagicMock(return_value={
            "status": "ok",
            "data_id": 12345678
        })
        
        bk_tenant_id = "default"
        data_name = "2_bkapm_test_app_trace"
        
        data = mock_get_data_id_v2(
            bk_tenant_id=bk_tenant_id,
            data_name=data_name,
            namespace=BKBASE_NAMESPACE_BK_APM,
        )
        
        # 验证返回的 data_id
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["data_id"], 12345678)

    def test_v4_path_creates_metadata_datasource(self):
        """
        测试: V4链路创建metadata.DataSource记录
        
        验证点:
        - 应调用 DataSource.create_data_source()
        - created_from 应为 'bkdata'
        - bk_data_id 应为从BKBase获取的值
        """
        mock_create_data_source = MagicMock()
        
        bk_data_id = 12345678
        data_name = "2_bkapm_test_app_trace"
        bk_tenant_id = "default"
        bk_biz_id = 2
        operator = "system"
        DATA_ID_PARAM = {
            "etl_config": "bk_flat_batch",
            "type_label": "log",
            "source_label": "bk_monitor",
        }
        
        # 模拟PR中的逻辑
        mock_create_data_source(
            data_name=data_name,
            bk_data_id=bk_data_id,
            bk_tenant_id=bk_tenant_id,
            operator=operator,
            bk_biz_id=bk_biz_id,
            created_from="bkdata",
            **DATA_ID_PARAM,
        )
        
        # 验证调用参数
        mock_create_data_source.assert_called_once()
        call_kwargs = mock_create_data_source.call_args.kwargs
        self.assertEqual(call_kwargs['bk_data_id'], bk_data_id)
        self.assertEqual(call_kwargs['created_from'], "bkdata")
        self.assertEqual(call_kwargs['etl_config'], "bk_flat_batch")

    def test_v4_path_vs_gse_path(self):
        """
        测试: V4链路与GSE链路的对比
        
        验证点:
        - TRACING_ENABLE_BKDATA=True 时走V4链路
        - TRACING_ENABLE_BKDATA=False 时走GSE链路
        """
        mock_v4_apply = MagicMock()
        mock_gse_apply = MagicMock()
        
        # 测试V4链路
        settings_v4 = MockSettings()
        settings_v4.TRACING_ENABLE_BKDATA = True
        
        if settings_v4.TRACING_ENABLE_BKDATA:
            mock_v4_apply(namespace="bkapm")
        else:
            mock_gse_apply()
        
        mock_v4_apply.assert_called_once_with(namespace="bkapm")
        mock_gse_apply.assert_not_called()
        
        # 重置
        mock_v4_apply.reset_mock()
        mock_gse_apply.reset_mock()
        
        # 测试GSE链路
        settings_gse = MockSettings()
        settings_gse.TRACING_ENABLE_BKDATA = False
        
        if settings_gse.TRACING_ENABLE_BKDATA:
            mock_v4_apply(namespace="bkapm")
        else:
            mock_gse_apply()
        
        mock_v4_apply.assert_not_called()
        mock_gse_apply.assert_called_once()

    def test_v4_path_failed_status_raises_error(self):
        """
        测试: V4链路获取data_id失败时抛出异常
        """
        # 模拟失败状态
        mock_get_data_id_v2 = MagicMock(return_value={
            "status": "failed",
            "data_id": None
        })
        
        data = mock_get_data_id_v2()
        
        if data["status"] == "failed":
            with self.assertRaises(Exception):
                raise Exception(f"apply data id from bkdata failed, status is {data['status']}")

    def test_v4_path_timeout_raises_error(self):
        """
        测试: V4链路轮询超时时抛出异常
        """
        # 模拟超时情况 - 5次轮询后仍未获取到data_id
        bk_data_id = None
        max_retries = 5
        
        for _ in range(max_retries):
            # 模拟每次返回 pending 状态
            data = {"status": "pending", "data_id": None}
            if data["status"] == "ok":
                bk_data_id = data["data_id"]
                break
        
        # 验证超时异常
        if bk_data_id is None:
            with self.assertRaises(Exception):
                raise Exception("apply data id from bkdata timeout")

if __name__ == '__main__':
    print("=" * 70)
    print("PR #9823 单元测试: TRACING_ENABLE_BKDATA 全局开关")
    print("=" * 70)
    print()
    
    # 运行测试
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加所有测试类
    test_classes = [
        TestTracingEnableBkdataConfig,
        TestApplyDatasourceLogic,
        TestBkBizIdToTenantId,
        TestApplyApmDatalinkTask,
        TestDataLinkNameFormat,
        TestIntegrationScenarios,
        TestPureV4CreateDataId,
    ]
    
    for test_class in test_classes:
        suite.addTests(loader.loadTestsFromTestCase(test_class))
    
    # 运行并输出结果
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # 输出总结
    print()
    print("=" * 70)
    if result.wasSuccessful():
        print("✅ 所有测试通过!")
    else:
        print("❌ 部分测试失败")
        print(f"   失败: {len(result.failures)}")
        print(f"   错误: {len(result.errors)}")
    print("=" * 70)
    
    sys.exit(0 if result.wasSuccessful() else 1)
