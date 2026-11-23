def navigation(request):
    if not request.user.is_authenticated:
        return {'current_role': ''}
    return {'current_role': 'admin' if request.user.is_superuser else request.user.role}
