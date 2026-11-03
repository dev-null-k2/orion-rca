# How to search the logs

- Every request carries a `corr_id` that every service logs. Find one failing request first,
  then follow its `corr_id` across services instead of counting errors.
- The loudest error is rarely the cause. `carrier-gateway` logs `CAR-0429 RATE_LIMITED` warnings all day.
- Compare the incident window with the day before before calling an error "new".
