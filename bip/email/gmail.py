# Module handling the connection with the gmail API
import datetime
import json
import re
import html2text
import base64

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from googleapiclient.errors import HttpError
from googleapiclient.discovery import build

from bip import utils
from bip.config import test_email

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def credentials(user_email):
    """
    Get up-to-date credentials for the Gmail API.
    """
    # the gmail json token stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    try:
        token = utils.get_secret(f"{user_email}-gmail-token")
        creds = Credentials.from_authorized_user_info(
            json.loads(token), SCOPES)
    except FileNotFoundError:
        creds = None
    # If there are no (valid) credentials available, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(
                json.loads(utils.get_secret('gmail-credentials')),
                SCOPES)
            creds = flow.run_local_server(port=0)
        # Save the credentials for the next run
        utils.set_secret(f"{user_email}-gmail-token", creds.to_json())
    return creds


def gmail_api_client(user_email):
    """Get the gmail API client."""
    return build('gmail', 'v1', credentials=credentials(user_email))


def get_header_value(headers, name):
    """Get the value of a header from the list of headers."""
    for header in headers:
        if header['name'] == name:
            return header['value']
    return None


def _clean(text):
    """Clean the text of a message.
    """
    # Turn any URL into a special token
    text = re.sub(r'http\S+', '<URL>', text)
    # Any character repeated more than 3 times is replaced by 3 of them
    text = re.sub(r'(.)\1{3,}', r'\1\1\1', text)
    # Any two characters repeated more than 3 times is replaced by 2 of them
    text = re.sub(r'(..)\1{3,}', r'\1\1', text)
    return text


def get_message_text_from_payload(message_part):
    """Get the message text from the message payload."""
    body = message_part['body']
    result = u''
    if 'data' in body:
        raw_data = base64.urlsafe_b64decode(body['data']).decode('utf-8')
        if message_part['mimeType'] == 'text/html':
            h = html2text.HTML2Text()
            h.ignore_links = True
            h.ignore_images = True
            result = h.handle(raw_data)
        elif message_part['mimeType'] == 'text/plain':
            result = raw_data
    result = _clean(result)
    parts = message_part.get('parts', [])
    for part in parts:
        result += get_message_text_from_payload(part)
    return result


def _display_thread(thread):
    """Display the thread's subject, and for each message,
    display the sender and body."""
    subject = get_header_value(thread['messages'][0]['payload']['headers'],
                               'Subject')
    print(f"====\nSubject: {subject}")
    for message in thread['messages']:
        sender = get_header_value(message['payload']['headers'], 'From')
        body = get_message_text_from_payload(message['payload'])
        print('\nSender: %s\nBody: %s' % (sender, body))


def get_last_threads(gmail_api_client, number_of_threads):
    """Get the last threads from Gmail.

    Doc: https://developers.google.com/gmail/api/v1/reference/users/threads/
    """
    try:
        response = (gmail_api_client.users().threads()
                    .list(userId='me', maxResults=number_of_threads)
                    .execute())
        threads = response['threads']
        result = []
        for thread in threads:
            thread_id = thread['id']
            thread = (gmail_api_client.users().threads()
                      .get(userId='me', id=thread_id)
                      .execute())
            result.append(thread)
        return result
    except HttpError as error:
        print('An error occurred: %s' % error)


def _get_message(gmail_client, message_head):
    """Get message from a message head returned by the gmail 'list' API call"""
    return (gmail_client.users().messages()
            .get(userId='me', id=message_head['id'])
            .execute())


def get_last_emails(gmail_client, last_update_date):
    """Get the last emails from Gmail

    Doc: https://developers.google.com/gmail/api/v1/reference/users/messages/
    :param gmail_client: the gmail API client
    :param last_update_date: the last update date
    """
    try:
        last_date = last_update_date.strftime('%Y/%m/%d')
        response = (gmail_client.users().messages()
                    .list(userId='me', q=f"after:{last_date}")
                    .execute())
        message_heads = response['messages']
        if not message_heads:
            return []
        return list(
            map(lambda x: _get_message(gmail_client, x), message_heads))
    except HttpError as error:
        print('An error occurred: %s' % error)


def test_gmail_api():
    client = gmail_api_client(test_email)
    # retrieve the last 3 threads from Gmail
    last_threads = get_last_threads(client, 3)

    # display the last 3 threads
    for thread in last_threads:
        _display_thread(thread)


if __name__ == '__main__':
    print('Test')
    # list messages' subjects from messages after March 29, 2023 at 9
    retrieval_date = datetime.datetime(2023, 3, 28, 9, 0, 0)
    messages = get_last_emails(gmail_api_client(test_email),
                               retrieval_date)
    for message in messages:
        print(message['snippet'])


def email_batches_by_query(gmail_client, query, batch_size=100):
    """Get emails between two dates and return them in batches via a generator.

    :param gmail_client: the gmail API client
    :param query: the query to use
    :param batch_size: the batch size
    """
    # get the first batch of emails
    response = (gmail_client.users().messages()
                .list(userId='me', q=query)
                .execute())
    while True:
        message_heads = response['messages']
        for i in range(0, len(message_heads), batch_size):
            yield list(map(lambda x: _get_message(gmail_client, x),
                           message_heads[i:i + batch_size]))
        if 'nextPageToken' not in response:
            break
        response = (gmail_client.users().messages()
                    .list(userId='me',
                          q=query,
                          pageToken=response['nextPageToken'])
                    .execute())


def email_batches_by_dates(gmail_client, start_date, end_date, batch_size=100):
    """Get emails between two dates and return them in batches via a generator.

    :param gmail_client: the gmail API client
    :param start_date: the start date, inclusive
    :param end_date: the end date, exclusive
    :param batch_size: the batch size
    """
    start_date = start_date.strftime('%Y/%m/%d')
    end_date = end_date.strftime('%Y/%m/%d')
    return email_batches_by_query(gmail_client,
                                  f"after:{start_date} before:{end_date}",
                                  batch_size)
