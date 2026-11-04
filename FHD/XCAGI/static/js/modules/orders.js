let ordersTableEventsBound = false;

function bindOrdersTableEvents() {
    if (ordersTableEventsBound) return;
    ordersTableEventsBound = true;

    const tbody = document.getElementById('ordersTableBody');
    if (!tbody) return;
    tbody.addEventListener('click', function(e) {
        const target = e.target.closest('[data-action="delete-order"][data-order-id]');
        if (!target) return;
        deleteOrder(target.getAttribute('data-order-id'));
    });
}

function loadOrders() {
    fetch(API_BASE + '/api/orders')
        .then(r => r.json())
        .then(data => {
            if (data.success) renderOrders(data.data || []);
        });
}

function renderOrders(orders) {
    bindOrdersTableEvents();
    const tbody = document.getElementById('ordersTableBody');
    tbody.textContent = '';
    if (!orders || orders.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="empty-state">暂无出货记录</td></tr>';
        return;
    }
    orders.forEach(o => {
        const tr = document.createElement('tr');

        const orderNumber = document.createElement('td');
        orderNumber.textContent = o.order_number || '';
        tr.appendChild(orderNumber);

        const customerName = document.createElement('td');
        customerName.textContent = o.customer_name || '';
        tr.appendChild(customerName);

        const date = document.createElement('td');
        date.textContent = o.date || '';
        tr.appendChild(date);

        const amount = document.createElement('td');
        amount.textContent = `¥${Number(o.total_amount || 0)}`;
        tr.appendChild(amount);

        const statusTd = document.createElement('td');
        const badge = document.createElement('span');
        badge.className = 'badge badge-success';
        badge.textContent = o.status || '已完成';
        statusTd.appendChild(badge);
        tr.appendChild(statusTd);

        const actionTd = document.createElement('td');
        const deleteBtn = document.createElement('button');
        deleteBtn.className = 'btn btn-danger btn-sm';
        deleteBtn.textContent = '删除';
        deleteBtn.setAttribute('data-action', 'delete-order');
        deleteBtn.setAttribute('data-order-id', encodeURIComponent(o.id || ''));
        actionTd.appendChild(deleteBtn);
        tr.appendChild(actionTd);

        tbody.appendChild(tr);
    });
}

function deleteOrder(recordId) {
    const decodedRecordId = decodeURIComponent(recordId);
    if (!confirm('确定要删除这条出货记录吗？此操作不可恢复！')) return;
    
    fetch(API_BASE + '/api/shipment/orders/' + encodeURIComponent(decodedRecordId), {
        method: 'DELETE'
    }).then(r => r.json()).then(data => {
        if (data.success) {
            alert(data.message);
            loadOrders();
        } else {
            alert('删除失败: ' + data.message);
        }
    }).catch(e => {
        alert('删除失败: ' + e.message);
    });
}

function clearAllOrders() {
    if (!confirm('确定要清空所有出货记录吗？此操作不可恢复！')) return;
    
    fetch(API_BASE + '/api/orders/clear-all', {
        method: 'DELETE'
    }).then(r => r.json()).then(data => {
        if (data.success) {
            alert(data.message);
            loadOrders();
        } else {
            alert('清空失败: ' + data.message);
        }
    }).catch(e => {
        alert('清空失败: ' + e.message);
    });
}

function searchOrders() {
    loadOrders();
}
