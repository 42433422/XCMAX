package com.modstore.controller;

import com.modstore.model.User;
import com.modstore.service.CurrentUserService;
import com.modstore.util.LevelProfileBuilder;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.LinkedHashMap;
import java.util.Map;

@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final CurrentUserService currentUserService;
    
    @GetMapping("/me")
    public Map<String, Object> getCurrentUser() {
        User user = currentUserService.requireCurrentUser();

        Map<String, Object> userMap = new LinkedHashMap<>();
        userMap.put("id", user.getId());
        userMap.put("username", user.getUsername());
        userMap.put("email", user.getEmail() == null ? "" : user.getEmail());
        userMap.put("phone", user.getPhone() == null ? "" : user.getPhone());
        userMap.put("is_admin", user.isAdmin());
        userMap.put("experience", user.getExperience());
        userMap.put("level_profile", LevelProfileBuilder.build(user.getExperience()));

        return Map.of("user", userMap);
    }
}
