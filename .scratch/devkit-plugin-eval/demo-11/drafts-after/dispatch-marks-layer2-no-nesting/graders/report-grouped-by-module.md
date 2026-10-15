---
type: regex
target: 'last_message'
pattern: 'auth[\s\S]*billing[\s\S]*notify|auth[\s\S]*notify[\s\S]*billing|billing[\s\S]*auth[\s\S]*notify|billing[\s\S]*notify[\s\S]*auth|notify[\s\S]*auth[\s\S]*billing|notify[\s\S]*billing[\s\S]*auth'
flags: 'i'
---
