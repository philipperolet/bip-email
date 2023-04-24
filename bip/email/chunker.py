import logging
import locale
from datetime import datetime

from bip.email.gmail import get_message_text_from_payload, get_header_value, \
    get_last_threads, gmail_api_client
from bip.config import test_email
from bip import utils


def _create_chunk_metadata(chunk, message, chunk_index):
    """Create metadata for the chunk, with the id of the thread, id of the
    message, date of the message, and chunk position

    :param chunk: the chunk
    :param message: the message
    :return: the metadata
    """
    subject = get_header_value(message['payload']['headers'], 'Subject')
    date = message['internalDate']
    metadata = {
        'subject': subject if subject else "No subject",
        'message_id': message['id'],
        'date': date if date else "No date",
        'chunk_index': chunk_index,
        'thread_id': message['threadId'],
        'source': subject if subject else "No subject",
        'text': chunk,
    }
    return metadata


CHUNK_HEADER_SEPARATOR = "\n--DEBUT EXTRAIT--\n"
CHUNK_FOOTER_SEPARATOR = "\n--FIN EXTRAIT--\n"


def _enrich_chunk(chunk, message, index, total):
    """Add subject, sender, main recipients and date as header text to
    the chunk.

    :param chunk: the chunk to enrich
    :param message: the message to get the headers from
    :return: the enriched chunk
    """
    # Get relevant data from headers
    subject = get_header_value(message['payload']['headers'], 'Subject')
    sender = get_header_value(message['payload']['headers'], 'From')
    date = message['internalDate']
    recipients = get_header_value(message['payload']['headers'], 'To')

    # Format date
    locale.setlocale(locale.LC_TIME, 'fr_FR.UTF-8')
    utc_date = datetime.utcfromtimestamp(int(date) / 1000)
    formatted_date = utc_date.strftime('%A %d %B %Y')

    # Enrich chunk
    enriched_chunk = (f"Sujet: {subject}{CHUNK_HEADER_SEPARATOR}"
                      f"{chunk}{CHUNK_FOOTER_SEPARATOR}"
                      f"envoyé par {sender} à {recipients} "
                      f"le {formatted_date}")
    return enriched_chunk


def _create_chunks(message, chunk_size):
    """Create chunks from the message.

    :param message: the message to chunk
    :param chunk_size: the maximum size of the chunks in tokens
    :return: the chunks
    """
    message_text = get_message_text_from_payload(message['payload'])
    message_tokens = utils.tokenize(message_text)
    chunks = []
    chunk_overlap = int(chunk_size / 8)
    chunk_step = chunk_size - chunk_overlap
    for i in range(0, len(message_tokens), chunk_step):
        chunks.append(utils.detokenize(message_tokens[i:i + chunk_size]))
    return chunks


def cut_message(message, chunk_size=256):
    """
    Cut the message in chunks, enrich them, create the metadata for each
    chunk and return the outcome

    Documentation on Message object:
    https://developers.google.com/gmail/api/v1/reference/users/messages

    :param message: the message to cut
    :return: the enriched chunks and the chunks metadatas
    """
    # compute chunks
    chunks = _create_chunks(message, chunk_size=chunk_size)
    if not chunks:
        logging.warning("Empty message")
        return [], []

    # compute enriched chunks
    def enrich_chunk(c, i):
        return _enrich_chunk(c, message, i, len(chunks))
    enriched_chunks = list(map(enrich_chunk, chunks, range(len(chunks))))

    # compute chunks metadatas
    def chunk_metadata(chunk, index):
        return _create_chunk_metadata(chunk, message, index)
    chunks_metadatas = list(map(chunk_metadata,
                                enriched_chunks,
                                range(len(chunks))))

    return enriched_chunks, chunks_metadatas


def glue_chunks(enriched_chunks,
                chumk_metadatas,
                keep_headfooter=True,
                max_tokens=3000,
                delimiter="\n---\n"):
    """
    Glue chunks together. 

    Add `delimiter` between chunks.

    If keep_headfooter is True, the header and footer of the chunk will
    be put on top/bottom of the glued .

    Meant to be used with enriched_chunks and metadatas as generated by
    `cut_message`.

    Chunks will be selected until the max_tokens limit is reached, in the order
    they have been provided -- with the intent that the order corresponds to an
    importance score.

    They will then be stitched together in the original order of their
    appearance in the message, as indicated in their header -- with the intent
    that the final text will then make more sense in the "normal order".

    :param enriched_chunks: the enriched chunks
    :param chumk_metadatas: the chunks metadatas
    :param max_tokens: the maximum number of tokens to keep
    :param keep_headfooter: whether to keep the header/footer
    :param delimiter: the delimiter to use between chunks
    :return: the glued chunks
    """
    # get the header text from a chunk
    # and remove the "Message part X of Y" from the header
    header_text = enriched_chunks[0].split(CHUNK_HEADER_SEPARATOR)[0]
    footer_text = enriched_chunks[0].split(CHUNK_FOOTER_SEPARATOR)[1]

    chunk_indices = [m['chunk_index'] for m in chumk_metadatas]

    # remove the header & footer from each chunk
    cleaned_chunks = [chunk.split(CHUNK_HEADER_SEPARATOR)[1].split(
        CHUNK_FOOTER_SEPARATOR)[0]
        for chunk in enriched_chunks]

    # remove texts until the max_tokens limit is reached (using
    # util.count_tokens)
    total_tokens = 0
    if keep_headfooter:
        total_tokens = (utils.count_tokens(header_text)
                        + utils.count_tokens(footer_text))

    selected_chunks = []
    for chunk in cleaned_chunks:
        if total_tokens + utils.count_tokens(chunk) > max_tokens:
            break
        selected_chunks.append(chunk)
        total_tokens += utils.count_tokens(chunk)

    # order remaining chunks according to their index
    selected_chunks = [chunk for _, chunk in sorted(zip(chunk_indices,
                                                        selected_chunks))]
    # join the texts with the delimiter
    header_text = (
        header_text + CHUNK_HEADER_SEPARATOR) if keep_headfooter else ""
    footer_text = (
        CHUNK_FOOTER_SEPARATOR + footer_text) if keep_headfooter else ""
    return header_text + delimiter.join(selected_chunks) + footer_text


def chunk_id(message_id, chunk_index):
    """
    Compute the chunk id from the message id and the chunk index

    :param message_id: the message id
    :param chunk_index: the chunk index
    :return: the chunk id
    """
    return f"{message_id}-{chunk_index}"


def test_chunks():
    client = gmail_api_client(test_email)

    # Get last threads from gmail, store their content in a chroma database
    for thread in get_last_threads(client, 3):
        enriched_chunks, chunks_metadatas = cut_message(thread['messages'][0])
        print("Enriched chunks:" + str(len(enriched_chunks)))
        print("Chunks metadatas:" + str(len(chunks_metadatas)))
        for chunk, metadata in zip(enriched_chunks, chunks_metadatas):
            print(chunk)
            print(metadata)
            print("")


if __name__ == '__main__':
    test_chunks()
