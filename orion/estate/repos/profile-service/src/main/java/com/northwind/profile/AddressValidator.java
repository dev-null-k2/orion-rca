package com.northwind.profile;

/** Validates postal addresses. */
public class AddressValidator {

    private static final int MAX_LINE_LENGTH = 30;

    public void validate(Address address) {
        if (address.getLine1().length() > MAX_LINE_LENGTH) {
            throw new IllegalArgumentException("address line1 longer than " + MAX_LINE_LENGTH);
        }
    }
}
