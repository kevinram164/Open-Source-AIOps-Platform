# Coroot Integration

Phase 3: abstraction layer cho Coroot API.

**Giả định**: Coroot deployed trong namespace `coroot`. API endpoints sẽ được xác nhận qua Phase 0 discovery.

Planned client methods:
- `get_service_topology(namespace, service)`
- `get_dependencies(service)`
- `get_log_summary(namespace, service, time_range)`
- `get_trace_summary(namespace, service, time_range)`
- `get_application_health(namespace, service)`
