from rest_framework.pagination import PageNumberPagination


class DefaultPagination(PageNumberPagination):
    """Page-number pagination that lets clients pick a page size within limits."""

    page_size_query_param = "page_size"
    max_page_size = 100
