# ruff: noqa
"""Warehouse and storage-location inventory operations."""
from __future__ import annotations
import importlib
import logging
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from app.utils.operational_errors import RECOVERABLE_ERRORS
logger = logging.getLogger('app.services.inventory_service')

def _facade():
    return importlib.import_module('app.services.inventory_service')

class InventoryWarehouseMixin:
    if TYPE_CHECKING:

        def __getattr__(self, name: str) -> Any:
            ...

    @staticmethod
    def _decimal_to_float(value: Any) -> Any:
        if isinstance(value, Decimal):
            return float(value)
        return value

    @staticmethod
    def _model_to_dict(model: Any) -> dict[str, Any]:
        if model is None:
            return {}
        result = {}
        for col in model.__table__.columns:
            value = getattr(model, col.name)
            result[col.name] = InventoryWarehouseMixin._decimal_to_float(value)
        return result

    def get_warehouses(self, status: str | None=None) -> dict[str, Any]:
        with _facade().get_db() as db:
            query = db.query(_facade().Warehouse)
            if status:
                query = query.filter(_facade().Warehouse.status == status)
            warehouses = query.order_by(_facade().Warehouse.code).all()
            return {'success': True, 'data': [self._model_to_dict(w) for w in warehouses], 'count': len(warehouses)}

    def get_warehouse(self, warehouse_id: int) -> dict[str, Any]:
        with _facade().get_db() as db:
            warehouse = db.query(_facade().Warehouse).filter(_facade().Warehouse.id == warehouse_id).first()
            if not warehouse:
                return {'success': False, 'message': '仓库不存在'}
            return {'success': True, 'data': self._model_to_dict(warehouse)}

    def create_warehouse(self, data: dict[str, Any]) -> dict[str, Any]:
        with _facade().get_db() as db:
            try:
                warehouse = _facade().Warehouse(code=data.get('code'), name=data.get('name'), type=data.get('type'), address=data.get('address'), manager=data.get('manager'), status=data.get('status', 'active'), created_at=datetime.now())
                db.add(warehouse)
                db.commit()
                db.refresh(warehouse)
                return {'success': True, 'data': self._model_to_dict(warehouse)}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error('创建仓库失败: %s', e)
                return {'success': False, 'message': str(e)}

    def update_warehouse(self, warehouse_id: int, data: dict[str, Any]) -> dict[str, Any]:
        with _facade().get_db() as db:
            try:
                warehouse = db.query(_facade().Warehouse).filter(_facade().Warehouse.id == warehouse_id).first()
                if not warehouse:
                    return {'success': False, 'message': '仓库不存在'}
                for (key, value) in data.items():
                    if hasattr(warehouse, key):
                        setattr(warehouse, key, value)
                warehouse.updated_at = datetime.now()
                db.commit()
                db.refresh(warehouse)
                return {'success': True, 'data': self._model_to_dict(warehouse)}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error('更新仓库失败: %s', e)
                return {'success': False, 'message': str(e)}

    def delete_warehouse(self, warehouse_id: int) -> dict[str, Any]:
        with _facade().get_db() as db:
            try:
                warehouse = db.query(_facade().Warehouse).filter(_facade().Warehouse.id == warehouse_id).first()
                if not warehouse:
                    return {'success': False, 'message': '仓库不存在'}
                warehouse.status = 'deleted'
                db.commit()
                return {'success': True, 'message': '仓库已删除'}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error('删除仓库失败: %s', e)
                return {'success': False, 'message': str(e)}

    def get_storage_locations(self, warehouse_id: int, status: str | None=None) -> dict[str, Any]:
        with _facade().get_db() as db:
            query = db.query(_facade().StorageLocation).filter(_facade().StorageLocation.warehouse_id == warehouse_id)
            if status:
                query = query.filter(_facade().StorageLocation.status == status)
            locations = query.order_by(_facade().StorageLocation.code).all()
            return {'success': True, 'data': [self._model_to_dict(loc) for loc in locations], 'count': len(locations)}

    def create_storage_location(self, data: dict[str, Any]) -> dict[str, Any]:
        with _facade().get_db() as db:
            try:
                location = _facade().StorageLocation(warehouse_id=data.get('warehouse_id'), code=data.get('code'), name=data.get('name'), max_capacity=self._decimal_to_float(data.get('max_capacity')), current_capacity=self._decimal_to_float(data.get('current_capacity', 0)), status=data.get('status', 'active'), created_at=datetime.now())
                db.add(location)
                db.commit()
                db.refresh(location)
                return {'success': True, 'data': self._model_to_dict(location)}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error('创建库位失败: %s', e)
                return {'success': False, 'message': str(e)}

    def update_storage_location(self, location_id: int, data: dict[str, Any]) -> dict[str, Any]:
        with _facade().get_db() as db:
            try:
                location = db.query(_facade().StorageLocation).filter(_facade().StorageLocation.id == location_id).first()
                if not location:
                    return {'success': False, 'message': '库位不存在'}
                updatable = ['code', 'name', 'max_capacity', 'status']
                for field in updatable:
                    if field in data:
                        value = data[field]
                        if field == 'max_capacity':
                            value = self._decimal_to_float(value)
                        setattr(location, field, value)
                db.commit()
                db.refresh(location)
                return {'success': True, 'data': self._model_to_dict(location)}
            except RECOVERABLE_ERRORS as e:
                db.rollback()
                _facade().logger.error('更新库位失败: %s', e)
                return {'success': False, 'message': str(e)}
