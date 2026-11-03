package com.northwind.activation;

/** Writes service events through the stored procedure sp_insert_service_event. */
public class ServiceEventService {

    private final ServiceEventDao dao;

    public ServiceEventService(ServiceEventDao dao) {
        this.dao = dao;
    }

    public ServiceEvent create(ServiceEvent tx) {
        ErrorStatus status = dao.insert(tx);
        if (status.getCode() == 0) {
            return tx;
        }
        return null;
    }
}
