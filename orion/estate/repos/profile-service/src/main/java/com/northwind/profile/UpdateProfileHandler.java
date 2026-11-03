package com.northwind.profile;

/** Handles PUT /v2/accounts/{id}/profile. */
public class UpdateProfileHandler {

    private final ProfileRepository repository;
    private final AddressValidator addresses;
    private final Logger log = Logger.get("profile-service");

    public UpdateProfileHandler(ProfileRepository repository, AddressValidator addresses) {
        this.repository = repository;
        this.addresses = addresses;
    }

    public Result handle(String accountId, ProfileUpdate update) {
        try {
            addresses.validate(update.getAddress());
            repository.update(accountId, update);
            return Result.ok();
        } catch (Exception e) {
            log.error("profile update failed account=" + accountId);
            return Result.error("PRF-2001", "Your changes could not be saved");
        }
    }
}
