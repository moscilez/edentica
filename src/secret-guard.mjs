// Content submitted to AI must not contain recognizable credential material.
// Provider authentication uses server environment variables separately.
export function rejectCredentials(text){
 if(/sk-(?:proj-)?[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN(?: RSA| EC| OPENSSH)? PRIVATE KEY-----/.test(text))throw Object.assign(Error('Обнаружен возможный ключ или закрытый ключ. Удалите секреты из материала перед отправкой ИИ.'),{status:400});
}
