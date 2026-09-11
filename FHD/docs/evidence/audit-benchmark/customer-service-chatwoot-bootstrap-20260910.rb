def ensure_user(email, name)
  u = User.find_or_create_by!(email: email) { |x| x.password = "Passw0rd!2023"; x.name = name }
  u
end

def ensure_account(name, email, uname)
  a = Account.find_or_create_by!(name: name)
  u = ensure_user(email, uname)
  a.users << u unless a.users.include?(u)
  [a, u]
end

a1, u1 = ensure_account("R22-Acct-A", "agent1@r22.local", "Agent One")
a2, u2 = ensure_account("R22-Acct-B", "agent2@r22.local", "Agent Two")
sa = ensure_user("super@r22.local", "Super")
sa.update!(type: "SuperAdmin") unless sa.type == "SuperAdmin"

def tok_for(u)
  t = AccessToken.new(owner_type: "User", owner_id: u.id)
  t.save!
  t.token
end

puts "RESULTJSON " + JSON.generate(
  account_a: a1.id, user_a: u1.id, token_a: tok_for(u1),
  account_b: a2.id, user_b: u2.id, token_b: tok_for(u2),
  super_token: tok_for(sa)
)
