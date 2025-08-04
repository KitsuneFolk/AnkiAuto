The repository relies on using API of an Anki plugin that AI might not have the most recent knowledge of, for this reason the source code of AnkiConnect is attached below.

__init__.py
```
# Copyright 2016-2021 Alex Yatskov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import aqt

required_anki_version = (23, 10, 0)
anki_version = tuple(int(segment) for segment in aqt.appVersion.split("."))

if anki_version < required_anki_version:
    raise Exception(f"Minimum Anki version supported: {required_anki_version[0]}.{required_anki_version[1]}.{required_anki_version[2]}")

import base64
import glob
import hashlib
import inspect
import json
import os
import os.path
import platform
import re
import time
import unicodedata

import anki
import anki.exporting
import anki.storage
from anki.cards import Card
from anki.consts import MODEL_CLOZE
from anki.exporting import AnkiPackageExporter
from anki.importing import AnkiPackageImporter
from anki.notes import Note
from anki.errors import NotFoundError
from anki.scheduler.base import ScheduleCardsAsNew
from aqt.qt import Qt, QTimer, QMessageBox, QCheckBox

from .web import format_exception_reply, format_success_reply
from .edit import Edit
from . import web, util


#
# AnkiConnect
#

class AnkiConnect:
    def __init__(self):
        self.log = None
        self.timer = None
        self.server = web.WebServer(self.handler)

    def initLogging(self):
        logPath = util.setting('apiLogPath')
        if logPath is not None:
            self.log = open(logPath, 'w')

    def startWebServer(self):
        try:
            self.server.listen()

            # only keep reference to prevent garbage collection
            self.timer = QTimer()
            self.timer.timeout.connect(self.advance)
            self.timer.start(util.setting('apiPollInterval'))
        except:
            QMessageBox.critical(
                self.window(),
                'AnkiConnect',
                'Failed to listen on port {}.\nMake sure it is available and is not in use.'.format(util.setting('webBindPort'))
            )

    def save_model(self, models, ankiModel):
        models.update_dict(ankiModel)

    def logEvent(self, name, data):
        if self.log is not None:
            self.log.write('[{}]\n'.format(name))
            json.dump(data, self.log, indent=4, sort_keys=True)
            self.log.write('\n\n')
            self.log.flush()


    def advance(self):
        self.server.advance()


    def handler(self, request):
        self.logEvent('request', request)

        name = request.get('action', '')
        version = request.get('version', 4)
        params = request.get('params', {})
        key = request.get('key')

        try:
            if key != util.setting('apiKey') and name != 'requestPermission':
                raise Exception('valid api key must be provided')

            method = None

            for methodName, methodInst in inspect.getmembers(self, predicate=inspect.ismethod):
                apiVersionLast = 0
                apiNameLast = None

                if getattr(methodInst, 'api', False):
                    for apiVersion, apiName in getattr(methodInst, 'versions', []):
                        if apiVersionLast < apiVersion <= version:
                            apiVersionLast = apiVersion
                            apiNameLast = apiName

                    if apiNameLast is None and apiVersionLast == 0:
                        apiNameLast = methodName

                    if apiNameLast is not None and apiNameLast == name:
                        method = methodInst
                        break

            if method is None:
                raise Exception('unsupported action')

            api_return_value = methodInst(**params)
            reply = format_success_reply(version, api_return_value)

        except Exception as e:
            reply = format_exception_reply(version, e)

        self.logEvent('reply', reply)
        return reply


    def window(self):
        return aqt.mw


    def reviewer(self):
        reviewer = self.window().reviewer
        if reviewer is None:
            raise Exception('reviewer is not available')

        return reviewer


    def collection(self):
        collection = self.window().col
        if collection is None:
            raise Exception('collection is not available')

        return collection


    def decks(self):
        decks = self.collection().decks
        if decks is None:
            raise Exception('decks are not available')

        return decks


    def scheduler(self):
        scheduler = self.collection().sched
        if scheduler is None:
            raise Exception('scheduler is not available')

        return scheduler


    def database(self):
        database = self.collection().db
        if database is None:
            raise Exception('database is not available')

        return database


    def media(self):
        media = self.collection().media
        if media is None:
            raise Exception('media is not available')

        return media


    def getModel(self, modelName):
        model = self.collection().models.by_name(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))
        return model


    def getField(self, model, fieldName):
        fieldMap = self.collection().models.field_map(model)
        if fieldName not in fieldMap:
            raise Exception('field was not found in {}: {}'.format(model['name'], fieldName))
        return fieldMap[fieldName][1]


    def getTemplate(self, model, templateName):
        for ankiTemplate in model['tmpls']:
            if ankiTemplate['name'] == templateName:
                return ankiTemplate
        raise Exception('template was not found in {}: {}'.format(model['name'], templateName))


    def startEditing(self):
        self.window().requireReset()


    def createNote(self, note):
        collection = self.collection()

        model = collection.models.by_name(note['modelName'])
        if model is None:
            raise Exception('model was not found: {}'.format(note['modelName']))

        deck = collection.decks.by_name(note['deckName'])
        if deck is None:
            raise Exception('deck was not found: {}'.format(note['deckName']))

        ankiNote = anki.notes.Note(collection, model)
        ankiNote.note_type()['did'] = deck['id']
        if 'tags' in note:
            ankiNote.tags = note['tags']

        for name, value in note['fields'].items():
            for ankiName in ankiNote.keys():
                if name.lower() == ankiName.lower():
                    ankiNote[ankiName] = value
                    break

        self.addMediaFromNote(ankiNote, note)

        allowDuplicate = False
        duplicateScope = None
        duplicateScopeDeckName = None
        duplicateScopeCheckChildren = False
        duplicateScopeCheckAllModels = False

        if 'options' in note:
            options = note['options']
            if 'allowDuplicate' in options:
                allowDuplicate = options['allowDuplicate']
                if type(allowDuplicate) is not bool:
                    raise Exception('option parameter "allowDuplicate" must be boolean')
            if 'duplicateScope' in options:
                duplicateScope = options['duplicateScope']
            if 'duplicateScopeOptions' in options:
                duplicateScopeOptions = options['duplicateScopeOptions']
                if 'deckName' in duplicateScopeOptions:
                    duplicateScopeDeckName = duplicateScopeOptions['deckName']
                if 'checkChildren' in duplicateScopeOptions:
                    duplicateScopeCheckChildren = duplicateScopeOptions['checkChildren']
                    if type(duplicateScopeCheckChildren) is not bool:
                        raise Exception('option parameter "duplicateScopeOptions.checkChildren" must be boolean')
                if 'checkAllModels' in duplicateScopeOptions:
                    duplicateScopeCheckAllModels = duplicateScopeOptions['checkAllModels']
                    if type(duplicateScopeCheckAllModels) is not bool:
                        raise Exception('option parameter "duplicateScopeOptions.checkAllModels" must be boolean')

        duplicateOrEmpty = self.isNoteDuplicateOrEmptyInScope(
            ankiNote,
            deck,
            collection,
            duplicateScope,
            duplicateScopeDeckName,
            duplicateScopeCheckChildren,
            duplicateScopeCheckAllModels
        )

        if duplicateOrEmpty == 1:
            raise Exception('cannot create note because it is empty')
        elif duplicateOrEmpty == 2:
            if allowDuplicate:
                return ankiNote
            raise Exception('cannot create note because it is a duplicate')
        elif duplicateOrEmpty == 0:
            return ankiNote
        else:
            raise Exception('cannot create note for unknown reason')


    def isNoteDuplicateOrEmptyInScope(
        self,
        note,
        deck,
        collection,
        duplicateScope,
        duplicateScopeDeckName,
        duplicateScopeCheckChildren,
        duplicateScopeCheckAllModels
    ):
        # Returns: 1 if first is empty, 2 if first is a duplicate, 0 otherwise.

        # note.dupeOrEmpty returns if a note is a global duplicate with the specific model.
        # This is used as the default check, and the rest of this function is manually
        # checking if the note is a duplicate with additional options.
        if duplicateScope != 'deck' and not duplicateScopeCheckAllModels:
            return note.dupeOrEmpty() or 0

        # Primary field for uniqueness
        val = note.fields[0]
        if not val.strip():
            return 1
        csum = anki.utils.field_checksum(val)

        # Create dictionary of deck ids
        dids = None
        if duplicateScope == 'deck':
            did = deck['id']
            if duplicateScopeDeckName is not None:
                deck2 = collection.decks.by_name(duplicateScopeDeckName)
                if deck2 is None:
                    # Invalid deck, so cannot be duplicate
                    return 0
                did = deck2['id']

            dids = {did: True}
            if duplicateScopeCheckChildren:
                for kv in collection.decks.children(did):
                    dids[kv[1]] = True

        # Build query
        query = 'select id from notes where csum=?'
        queryArgs = [csum]
        if note.id:
            query += ' and id!=?'
            queryArgs.append(note.id)
        if not duplicateScopeCheckAllModels:
            query += ' and mid=?'
            queryArgs.append(note.mid)

        # Search
        for noteId in note.col.db.list(query, *queryArgs):
            if dids is None:
                # Duplicate note exists in the collection
                return 2
            # Validate that a card exists in one of the specified decks
            for cardDeckId in note.col.db.list('select did from cards where nid=?', noteId):
                if cardDeckId in dids:
                    return 2

        # Not a duplicate
        return 0

    def raiseNotFoundError(self, errorMsg):
        if anki_version < (2, 1, 55):
            raise NotFoundError(errorMsg)
        raise NotFoundError(errorMsg, None, None, None)

    def getCard(self, card_id: int) -> Card:
        try:
            return self.collection().get_card(card_id)
        except NotFoundError:
            self.raiseNotFoundError('Card was not found: {}'.format(card_id))

    def getNote(self, note_id: int) -> Note:
        try:
            return self.collection().get_note(note_id)
        except NotFoundError:
            self.raiseNotFoundError('Note was not found: {}'.format(note_id))

    def deckStatsToJson(self, due_tree):
        deckStats = {'deck_id': due_tree.deck_id,
                     'name': due_tree.name,
                     'new_count': due_tree.new_count,
                     'learn_count': due_tree.learn_count,
                     'review_count': due_tree.review_count}
        if anki_version > (2, 1, 46):
            # total_in_deck is not supported on lower Anki versions
            deckStats['total_in_deck'] = due_tree.total_in_deck
        return deckStats

    def collectDeckTreeChildren(self, parent_node):
        allNodes = {parent_node.deck_id: parent_node}
        for child in parent_node.children:
            for deckId, childNode in self.collectDeckTreeChildren(child).items():
                allNodes[deckId] = childNode
        return allNodes

    #
    # Miscellaneous
    #

    @util.api()
    def version(self):
        return util.setting('apiVersion')


    @util.api()
    def requestPermission(self, origin, allowed):
        results = {
                "permission": "denied",
        }

        if allowed:
            results = {
                    "permission": "granted",
                    "requireApikey": bool(util.setting('apiKey')),
                    "version": util.setting('apiVersion')
            }

        elif origin in util.setting('ignoreOriginList'):
            pass  # defaults to denied

        else:  # prompt the user
            msg = QMessageBox(None)
            msg.setWindowTitle("A website wants to access to Anki")
            msg.setText('"{}" requests permission to use Anki through AnkiConnect. Do you want to give it access?'.format(origin))
            msg.setInformativeText("By granting permission, you'll allow the website to modify your collection on your behalf, including the execution of destructive actions such as deck deletion.")
            msg.setWindowIcon(self.window().windowIcon())
            msg.setIcon(QMessageBox.Icon.Question)
            msg.setStandardButtons(QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No)
            msg.setDefaultButton(QMessageBox.StandardButton.No)
            msg.setCheckBox(QCheckBox(text='Ignore further requests from "{}"'.format(origin), parent=msg))
            if hasattr(Qt, 'WindowStaysOnTopHint'):
                # Qt5
                WindowOnTopFlag = Qt.WindowStaysOnTopHint
            elif hasattr(Qt, 'WindowType') and hasattr(Qt.WindowType, 'WindowStaysOnTopHint'):
                # Qt6
                WindowOnTopFlag = Qt.WindowType.WindowStaysOnTopHint
            msg.setWindowFlags(WindowOnTopFlag)
            pressedButton = msg.exec()

            if pressedButton == QMessageBox.StandardButton.Yes:
                config = aqt.mw.addonManager.getConfig(__name__)
                config["webCorsOriginList"] = util.setting('webCorsOriginList')
                config["webCorsOriginList"].append(origin)
                aqt.mw.addonManager.writeConfig(__name__, config)
                results = {
                    "permission": "granted",
                    "requireApikey": bool(util.setting('apiKey')),
                    "version": util.setting('apiVersion')
                }

            # if the origin isn't an empty string, the user clicks "No", and the ignore box is checked
            elif origin and pressedButton == QMessageBox.StandardButton.No and msg.checkBox().isChecked():
                config = aqt.mw.addonManager.getConfig(__name__)
                config["ignoreOriginList"] = util.setting('ignoreOriginList')
                config["ignoreOriginList"].append(origin)
                aqt.mw.addonManager.writeConfig(__name__, config)

            # else defaults to denied

        return results


    @util.api()
    def getProfiles(self):
        return self.window().pm.profiles()
    
    @util.api()
    def getActiveProfile(self):
        return self.window().pm.name

    @util.api()
    def loadProfile(self, name):
        if name not in self.window().pm.profiles():
            return False

        if self.window().isVisible():
            cur_profile = self.window().pm.name
            if cur_profile != name:
                self.window().unloadProfileAndShowProfileManager()

                def waiter():
                    # This function waits until main window is closed
                    # It's needed cause sync can take quite some time
                    # And if we call loadProfile until sync is ended things will go wrong
                    if self.window().isVisible():
                        QTimer.singleShot(1000, waiter)
                    else:
                        self.loadProfile(name)

                waiter()
        else:
            self.window().pm.load(name)
            self.window().loadProfile()
            self.window().profileDiag.closeWithoutQuitting()

        return True


    @util.api()
    def sync(self):
        mw = self.window()
        auth = mw.pm.sync_auth()
        if not auth:
            raise Exception("sync: auth not configured")
        out = mw.col.sync_collection(auth, mw.pm.media_syncing_enabled())
        accepted_sync_statuses = [out.NO_CHANGES, out.NORMAL_SYNC]
        if out.required not in accepted_sync_statuses:
            raise Exception(f"Sync status {out.required} not one of {accepted_sync_statuses} - see SyncCollectionResponse.ChangesRequired for list of sync statuses: https://github.com/ankitects/anki/blob/e41c4573d789afe8b020fab5d9d1eede50c3fa3d/proto/anki/sync.proto#L57-L65")
        mw.onSync()


    @util.api()
    def multi(self, actions):
        return list(map(self.handler, actions))


    @util.api()
    def getNumCardsReviewedToday(self):
        return self.database().scalar('select count() from revlog where id > ?', (self.scheduler().dayCutoff - 86400) * 1000)

    @util.api()
    def getNumCardsReviewedByDay(self):
        return self.database().all('select date(id/1000 - ?, "unixepoch", "localtime") as day, count() from revlog group by day order by day desc',
                                    int(time.strftime("%H", time.localtime(self.scheduler().dayCutoff))) * 3600)


    @util.api()
    def getCollectionStatsHTML(self, wholeCollection=True):
        stats = self.collection().stats()
        stats.wholeCollection = wholeCollection
        return stats.report()


    #
    # Decks
    #

    @util.api()
    def deckNames(self):
        return [x.name for x in self.decks().all_names_and_ids()]


    @util.api()
    def deckNamesAndIds(self):
        decks = {}
        for deck in self.deckNames():
            decks[deck] = self.decks().id(deck)

        return decks


    @util.api()
    def getDecks(self, cards):
        decks = {}
        for card in cards:
            did = self.database().scalar('select did from cards where id=?', card)
            deck = self.decks().get(did)['name']
            if deck in decks:
                decks[deck].append(card)
            else:
                decks[deck] = [card]

        return decks


    @util.api()
    def createDeck(self, deck):
        self.startEditing()
        return  self.decks().id(deck)


    @util.api()
    def changeDeck(self, cards, deck):
        self.startEditing()

        did = self.collection().decks.id(deck)
        mod = anki.utils.int_time()
        usn = self.collection().usn()

        # normal cards
        scids = anki.utils.ids2str(cards)
        # remove any cards from filtered deck first
        self.collection().sched.remFromDyn(cards)

        # then move into new deck
        self.collection().db.execute('update cards set usn=?, mod=?, did=? where id in ' + scids, usn, mod, did)


    @util.api()
    def deleteDecks(self, decks, cardsToo=False):
        if not cardsToo:
            # since f592672fa952260655881a75a2e3c921b2e23857 (2.1.28)
            # (see anki$ git log "-Gassert cardsToo")
            # you can't delete decks without deleting cards as well.
            # however, since 62c23c6816adf912776b9378c008a52bb50b2e8d (2.1.45)
            # passing cardsToo to `rem` (long deprecated) won't raise an error!
            # this is dangerous, so let's raise our own exception
            raise Exception("Since Anki 2.1.28 it's not possible "
                            "to delete decks without deleting cards as well")
        self.startEditing()
        decks = filter(lambda d: d in self.deckNames(), decks)
        for deck in decks:
            did = self.decks().id(deck)
            self.decks().remove([did])


    @util.api()
    def getDeckConfig(self, deck):
        if deck not in self.deckNames():
            return False

        collection = self.collection()
        did = collection.decks.id(deck)
        return collection.decks.config_dict_for_deck_id(did)


    @util.api()
    def saveDeckConfig(self, config):
        collection = self.collection()

        config['id'] = str(config['id'])
        config['mod'] = anki.utils.int_time()
        config['usn'] = collection.usn()
        if int(config['id']) not in [c['id'] for c in collection.decks.all_config()]:
            return False
        try:
            collection.decks.save(config)
            collection.decks.update_config(config)
        except:
            return False
        return True


    @util.api()
    def setDeckConfigId(self, decks, configId):
        configId = int(configId)
        for deck in decks:
            if not deck in self.deckNames():
                return False

        collection = self.collection()

        for deck in decks:
            try:
                did = str(collection.decks.id(deck))
                deck_dict = aqt.mw.col.decks.decks[did]
                deck_dict['conf'] = configId
                collection.decks.save(deck_dict)
            except:
                return False

        return True


    @util.api()
    def cloneDeckConfigId(self, name, cloneFrom='1'):
        configId = int(cloneFrom)
        collection = self.collection()
        if configId not in [c['id'] for c in collection.decks.all_config()]:
            return False

        config = collection.decks.get_config(configId)
        return collection.decks.add_config_returning_id(name, config)


    @util.api()
    def removeDeckConfigId(self, configId):
        collection = self.collection()
        if int(configId) not in [c['id'] for c in collection.decks.all_config()]:
            return False

        collection.decks.remove_config(configId)
        return True

    @util.api()
    def getDeckStats(self, decks):
        collection = self.collection()
        scheduler = self.scheduler()
        responseDict = {}
        deckIds = list(map(lambda d: collection.decks.id(d), decks))

        allDeckNodes = self.collectDeckTreeChildren(scheduler.deck_due_tree())
        for deckId, deckNode in allDeckNodes.items():
            if deckId in deckIds:
                responseDict[deckId] = self.deckStatsToJson(deckNode)
        return responseDict

    @util.api()
    def storeMediaFile(self, filename, data=None, path=None, url=None, skipHash=None, deleteExisting=True):
        if not (data or path or url):
            raise Exception('You must provide a "data", "path", or "url" field.')
        if data:
            mediaData = base64.b64decode(data)
        elif path:
            with open(path, 'rb') as f:
                mediaData = f.read()
        elif url:
            mediaData = util.download(url)

        if skipHash is None:
            skip = False
        else:
            m = hashlib.md5()
            m.update(mediaData)
            skip = skipHash == m.hexdigest()

        if skip:
            return None
        if deleteExisting:
            self.deleteMediaFile(filename)
        return self.media().writeData(filename, mediaData)


    @util.api()
    def retrieveMediaFile(self, filename):
        filename = os.path.basename(filename)
        filename = unicodedata.normalize('NFC', filename)
        filename = self.media().stripIllegal(filename)

        path = os.path.join(self.media().dir(), filename)
        if os.path.exists(path):
            with open(path, 'rb') as file:
                return base64.b64encode(file.read()).decode('ascii')

        return False


    @util.api()
    def getMediaFilesNames(self, pattern='*'):
        path = os.path.join(self.media().dir(), pattern)
        return [os.path.basename(p) for p in glob.glob(path)]


    @util.api()
    def deleteMediaFile(self, filename):
        self.media().trash_files([filename])

    @util.api()
    def getMediaDirPath(self):
        return os.path.abspath(self.media().dir())

    @util.api()
    def addNote(self, note):
        self.startEditing()
        ankiNote = self.createNote(note)

        collection = self.collection()
        nCardsAdded = collection.addNote(ankiNote)
        if nCardsAdded < 1:
            raise Exception('The field values you have provided would make an empty question on all cards.')

        return ankiNote.id


    def addMediaFromNote(self, ankiNote, note):
        audioObjectOrList = note.get('audio')
        self.addMedia(ankiNote, audioObjectOrList, util.MediaType.Audio)

        videoObjectOrList = note.get('video')
        self.addMedia(ankiNote, videoObjectOrList, util.MediaType.Video)

        pictureObjectOrList = note.get('picture')
        self.addMedia(ankiNote, pictureObjectOrList, util.MediaType.Picture)



    def addMedia(self, ankiNote, mediaObjectOrList, mediaType):
        if mediaObjectOrList is None:
            return

        if isinstance(mediaObjectOrList, list):
            mediaList = mediaObjectOrList
        else:
            mediaList = [mediaObjectOrList]

        for media in mediaList:
            if media is not None and len(media['fields']) > 0:
                try:
                    mediaFilename = self.storeMediaFile(media['filename'],
                                                        data=media.get('data'),
                                                        path=media.get('path'),
                                                        url=media.get('url'),
                                                        skipHash=media.get('skipHash'),
                                                        deleteExisting=media.get('deleteExisting'))

                    if mediaFilename is not None:
                        for field in media['fields']:
                            if field in ankiNote:
                                if mediaType is util.MediaType.Picture:
                                    ankiNote[field] += u'<img src="{}">'.format(mediaFilename)
                                elif mediaType is util.MediaType.Audio or mediaType is util.MediaType.Video:
                                    ankiNote[field] += u'[sound:{}]'.format(mediaFilename)

                except Exception as e:
                    errorMessage = str(e).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                    for field in media['fields']:
                        if field in ankiNote:
                            ankiNote[field] += errorMessage


    @util.api()
    def canAddNote(self, note):
        try:
            return bool(self.createNote(note))
        except:
            return False

    @util.api()
    def canAddNoteWithErrorDetail(self, note):
        try:
            return {
                'canAdd': bool(self.createNote(note))
            }
        except Exception as e:
            return {
                'canAdd': False,
                'error': str(e)
            }

    @util.api()
    def updateNoteFields(self, note):
        ankiNote = self.getNote(note['id'])

        self.startEditing()
        for name, value in note['fields'].items():
            if name in ankiNote:
                ankiNote[name] = value

        self.addMediaFromNote(ankiNote, note)

        self.collection().update_note(ankiNote, skip_undo_entry=True);


    @util.api()
    def updateNote(self, note):
        updated = False
        if 'fields' in note.keys():
            self.updateNoteFields(note)
            updated = True
        if 'tags' in note.keys():
            self.updateNoteTags(note['id'], note['tags'])
            updated = True
        if not updated:
            raise Exception('Must provide a "fields" or "tags" property.')

    @util.api()
    def updateNoteModel(self, note):
        """
        Update the model and fields of a given note.

        :param note: A dictionary containing note details, including 'id', 'modelName', 'fields', and 'tags'.
        """
        # Extract and validate the note ID
        note_id = note.get('id')
        if not note_id:
            raise ValueError("Note ID is required")

        # Extract and validate the new model name
        new_model_name = note.get('modelName')
        if not new_model_name:
            raise ValueError("Model name is required")

        # Extract and validate the new fields
        new_fields = note.get('fields')
        if not new_fields or not isinstance(new_fields, dict):
            raise ValueError("Fields must be provided as a dictionary")

        # Extract the new tags
        new_tags = note.get('tags', [])

        # Get the current note from the collection
        anki_note = self.getNote(note_id)

        # Get the new model from the collection
        collection = self.collection()
        new_model = collection.models.by_name(new_model_name)
        if not new_model:
            raise ValueError(f"Model '{new_model_name}' not found")

        # Update the note's model
        anki_note.mid = new_model['id']
        anki_note._fmap = collection.models.field_map(new_model)
        anki_note.fields = [''] * len(new_model['flds'])

        # Update the fields with new values
        for name, value in new_fields.items():
            for anki_name in anki_note.keys():
                if name.lower() == anki_name.lower():
                    anki_note[anki_name] = value
                    break

        # Update the tags
        anki_note.tags = new_tags

        # Update note to ensure changes are saved
        collection.update_note(anki_note, skip_undo_entry=True);

    @util.api()
    def updateNoteTags(self, note, tags):
        if type(tags) == str:
            tags = [tags]
        if type(tags) != list or not all([type(t) == str for t in tags]):
            raise Exception('Must provide tags as a list of strings')

        for old_tag in self.getNoteTags(note):
            self.removeTags([note], old_tag)
        for new_tag in tags:
            self.addTags([note], new_tag)


    @util.api()
    def getNoteTags(self, note):
        return self.getNote(note).tags


    @util.api()
    def addTags(self, notes, tags, add=True):
        self.startEditing()
        self.collection().tags.bulkAdd(notes, tags, add)


    @util.api()
    def removeTags(self, notes, tags):
        return self.addTags(notes, tags, False)


    @util.api()
    def getTags(self):
        return self.collection().tags.all()


    @util.api()
    def clearUnusedTags(self):
        self.collection().tags.registerNotes()


    @util.api()
    def replaceTags(self, notes, tag_to_replace, replace_with_tag):
        self.window().progress.start()

        for nid in notes:
            try:
                note = self.getNote(nid)
            except NotFoundError:
                continue

            if note.has_tag(tag_to_replace):
                note.remove_tag(tag_to_replace)
                note.add_tag(replace_with_tag)
                self.collection().update_note(note, skip_undo_entry=True);

        self.window().requireReset()
        self.window().progress.finish()
        self.window().reset()


    @util.api()
    def replaceTagsInAllNotes(self, tag_to_replace, replace_with_tag):
        self.window().progress.start()

        collection = self.collection()
        for nid in collection.db.list('select id from notes'):
            note = self.getNote(nid)
            if note.has_tag(tag_to_replace):
                note.remove_tag(tag_to_replace)
                note.add_tag(replace_with_tag)
                self.collection().update_note(note, skip_undo_entry=True);

        self.window().requireReset()
        self.window().progress.finish()
        self.window().reset()


    @util.api()
    def setEaseFactors(self, cards, easeFactors):
        couldSetEaseFactors = []
        for i, card in enumerate(cards):
            try:
                ankiCard = self.getCard(card)
            except NotFoundError:
                couldSetEaseFactors.append(False)
                continue

            couldSetEaseFactors.append(True)
            ankiCard.factor = easeFactors[i]
            self.collection().update_card(ankiCard, skip_undo_entry=True)

        return couldSetEaseFactors

    @util.api()
    def setSpecificValueOfCard(self, card, keys,
                               newValues, warning_check=False):
        if isinstance(card, list):
            print("card has to be int, not list")
            return False

        if not isinstance(keys, list) or not isinstance(newValues, list):
            print("keys and newValues have to be lists.")
            return False

        if len(newValues) != len(keys):
            print("Invalid list lengths.")
            return False

        for key in keys:
            if key in ["did", "id", "ivl", "lapses", "left", "mod", "nid",
                       "odid", "odue", "ord", "queue", "reps", "type", "usn"]:
                if warning_check is False:
                    return False

        result = []
        try:
            ankiCard = self.getCard(card)
            for i, key in enumerate(keys):
                setattr(ankiCard, key, newValues[i])
            self.collection().update_card(ankiCard, skip_undo_entry=True)
            result.append(True)
        except Exception as e:
            result.append([False, str(e)])
        return result


    @util.api()
    def getEaseFactors(self, cards):
        easeFactors = []
        for card in cards:
            try:
                ankiCard = self.getCard(card)
            except NotFoundError:
                easeFactors.append(None)
                continue

            easeFactors.append(ankiCard.factor)

        return easeFactors


    @util.api()
    def suspend(self, cards, suspend=True):
        for card in cards:
            if self.suspended(card) == suspend:
                cards.remove(card)

        if len(cards) == 0:
            return False

        scheduler = self.scheduler()
        self.startEditing()
        if suspend:
            scheduler.suspendCards(cards)
        else:
            scheduler.unsuspendCards(cards)

        return True


    @util.api()
    def unsuspend(self, cards):
        self.suspend(cards, False)


    @util.api()
    def suspended(self, card):
        card = self.getCard(card)
        return card.queue == -1


    @util.api()
    def areSuspended(self, cards):
        suspended = []
        for card in cards:
            try:
                suspended.append(self.suspended(card))
            except NotFoundError:
                suspended.append(None)

        return suspended


    @util.api()
    def areDue(self, cards):
        due = []
        for card in cards:
            if self.findCards('cid:{} is:new'.format(card)):
                due.append(True)
            else:
                date, ivl = self.collection().db.all('select id/1000.0, ivl from revlog where cid = ?', card)[-1]
                if ivl >= -1200:
                    due.append(bool(self.findCards('cid:{} is:due'.format(card))))
                else:
                    due.append(date - ivl <= time.time())

        return due


    @util.api()
    def getIntervals(self, cards, complete=False):
        intervals = []
        for card in cards:
            if self.findCards('cid:{} is:new'.format(card)):
                intervals.append(0)
            else:
                interval = self.collection().db.list('select ivl from revlog where cid = ?', card)
                if not complete:
                    interval = interval[-1]
                intervals.append(interval)

        return intervals



    @util.api()
    def modelNames(self):
        return [n.name for n in self.collection().models.all_names_and_ids()]


    @util.api()
    def createModel(self, modelName, inOrderFields, cardTemplates, css = None, isCloze = False):
        # https://github.com/dae/anki/blob/b06b70f7214fb1f2ce33ba06d2b095384b81f874/anki/stdmodels.py
        if len(inOrderFields) == 0:
            raise Exception('Must provide at least one field for inOrderFields')
        if len(cardTemplates) == 0:
            raise Exception('Must provide at least one card for cardTemplates')
        if modelName in [n.name for n in self.collection().models.all_names_and_ids()]:
            raise Exception('Model name already exists')

        collection = self.collection()
        mm = collection.models

        # Generate new Note
        m = mm.new(modelName)
        if isCloze:
            m['type'] = MODEL_CLOZE

        # Create fields and add them to Note
        for field in inOrderFields:
            fm = mm.new_field(field)
            mm.addField(m, fm)

        # Add shared css to model if exists. Use default otherwise
        if (css is not None):
            m['css'] = css

        # Generate new card template(s)
        cardCount = 1
        for card in cardTemplates:
            cardName = 'Card ' + str(cardCount)
            if 'Name' in card:
                cardName = card['Name']

            t = mm.new_template(cardName)
            cardCount += 1
            t['qfmt'] = card['Front']
            t['afmt'] = card['Back']
            mm.addTemplate(m, t)

        mm.add(m)
        return m


    @util.api()
    def modelNamesAndIds(self):
        models = {}
        for model in self.modelNames():
            models[model] = int(self.collection().models.by_name(model)['id'])

        return models


    @util.api()
    def findModelsById(self, modelIds):
        models = []
        for id in modelIds:
            model = self.collection().models.get(id)
            if model is None:
                raise Exception("model was not found: {}".format(id))
            else:
                models.append(model)
        return models

    @util.api()
    def findModelsByName(self, modelNames):
        models = []
        for name in modelNames:
            model = self.collection().models.by_name(name)
            if model is None:
                raise Exception("model was not found: {}".format(name))
            else:
                models.append(model)
        return models

    @util.api()
    def modelNameFromId(self, modelId):
        model = self.collection().models.get(modelId)
        if model is None:
            raise Exception('model was not found: {}'.format(modelId))
        else:
            return model['name']


    @util.api()
    def modelFieldNames(self, modelName):
        model = self.collection().models.by_name(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))
        else:
            return [field['name'] for field in model['flds']]


    @util.api()
    def modelFieldDescriptions(self, modelName):
        model = self.collection().models.by_name(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))
        else:
            try:
                return [field['description'] for field in model['flds']]
            except KeyError:
                # older versions of Anki don't have field descriptions
                return ['' for field in model['flds']]


    @util.api()
    def modelFieldFonts(self, modelName):
        model = self.getModel(modelName)

        fonts = {}
        for field in model['flds']:

            fonts[field['name']] = {
                'font': field['font'],
                'size': field['size'],
            }

        return fonts


    @util.api()
    def modelFieldsOnTemplates(self, modelName):
        model = self.collection().models.by_name(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))

        templates = {}
        for template in model['tmpls']:
            fields = []
            for side in ['qfmt', 'afmt']:
                fieldsForSide = []

                # based on _fieldsOnTemplate from aqt/clayout.py
                matches = re.findall('{{[^#/}]+?}}', template[side])
                for match in matches:
                    # remove braces and modifiers
                    match = re.sub(r'[{}]', '', match)
                    match = match.split(':')[-1]

                    # for the answer side, ignore fields present on the question side + the FrontSide field
                    if match == 'FrontSide' or side == 'afmt' and match in fields[0]:
                        continue
                    fieldsForSide.append(match)

                fields.append(fieldsForSide)

            templates[template['name']] = fields

        return templates


    @util.api()
    def modelTemplates(self, modelName):
        model = self.collection().models.by_name(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))

        templates = {}
        for template in model['tmpls']:
            templates[template['name']] = {'Front': template['qfmt'], 'Back': template['afmt']}

        return templates


    @util.api()
    def modelStyling(self, modelName):
        model = self.collection().models.by_name(modelName)
        if model is None:
            raise Exception('model was not found: {}'.format(modelName))

        return {'css': model['css']}


    @util.api()
    def updateModelTemplates(self, model):
        models = self.collection().models
        ankiModel = models.by_name(model['name'])
        if ankiModel is None:
            raise Exception('model was not found: {}'.format(model['name']))

        templates = model['templates']
        for ankiTemplate in ankiModel['tmpls']:
            template = templates.get(ankiTemplate['name'])
            if template:
                qfmt = template.get('Front')
                if qfmt:
                    ankiTemplate['qfmt'] = qfmt

                afmt = template.get('Back')
                if afmt:
                    ankiTemplate['afmt'] = afmt

        self.save_model(models, ankiModel)


    @util.api()
    def updateModelStyling(self, model):
        models = self.collection().models
        ankiModel = models.by_name(model['name'])
        if ankiModel is None:
            raise Exception('model was not found: {}'.format(model['name']))

        ankiModel['css'] = model['css']

        self.save_model(models, ankiModel)


    @util.api()
    def findAndReplaceInModels(self, modelName, findText, replaceText, front=True, back=True, css=True):
        if not modelName:
            ankiModel = self.collection().models.allNames()
        else:
            model = self.collection().models.by_name(modelName)
            if model is None:
                raise Exception('model was not found: {}'.format(modelName))
            ankiModel = [modelName]
        updatedModels = 0
        for model in ankiModel:
            model = self.collection().models.by_name(model)
            checkForText = False
            if css and findText in model['css']:
                checkForText = True
                model['css'] = model['css'].replace(findText, replaceText)
            for tmpls in model.get('tmpls'):
                if front and findText in tmpls['qfmt']:
                    checkForText = True
                    tmpls['qfmt'] = tmpls['qfmt'].replace(findText, replaceText)
                if back and findText in tmpls['afmt']:
                    checkForText = True
                    tmpls['afmt'] = tmpls['afmt'].replace(findText, replaceText)
            self.save_model(self.collection().models, model)
            if checkForText:
                updatedModels += 1
        return updatedModels


    @util.api()
    def modelTemplateRename(self, modelName, oldTemplateName, newTemplateName):
        mm = self.collection().models
        model = self.getModel(modelName)
        ankiTemplate = self.getTemplate(model, oldTemplateName)

        ankiTemplate['name'] = newTemplateName
        self.save_model(mm, model)


    @util.api()
    def modelTemplateReposition(self, modelName, templateName, index):
        mm = self.collection().models
        model = self.getModel(modelName)
        ankiTemplate = self.getTemplate(model, templateName)

        mm.reposition_template(model, ankiTemplate, index)
        self.save_model(mm, model)


    @util.api()
    def modelTemplateAdd(self, modelName, template):
        # "Name", "Front", "Back" borrows from `createModel`
        mm = self.collection().models
        model = self.getModel(modelName)
        name = template['Name']
        qfmt = template['Front']
        afmt = template['Back']

        # updates the template if it already exists
        for ankiTemplate in model['tmpls']:
            if ankiTemplate['name'] == name:
                ankiTemplate['qfmt'] = qfmt
                ankiTemplate['afmt'] = afmt
                return

        ankiTemplate = mm.new_template(name)
        ankiTemplate['qfmt'] = qfmt
        ankiTemplate['afmt'] = afmt
        mm.add_template(model, ankiTemplate)

        self.save_model(mm, model)


    @util.api()
    def modelTemplateRemove(self, modelName, templateName):
        mm = self.collection().models
        model = self.getModel(modelName)
        ankiTemplate = self.getTemplate(model, templateName)

        mm.remove_template(model, ankiTemplate)
        self.save_model(mm, model)


    @util.api()
    def modelFieldRename(self, modelName, oldFieldName, newFieldName):
        mm = self.collection().models
        model = self.getModel(modelName)
        field = self.getField(model, oldFieldName)

        mm.renameField(model, field, newFieldName)

        self.save_model(mm, model)


    @util.api()
    def modelFieldReposition(self, modelName, fieldName, index):
        mm = self.collection().models
        model = self.getModel(modelName)
        field = self.getField(model, fieldName)

        mm.reposition_field(model, field, index)

        self.save_model(mm, model)


    @util.api()
    def modelFieldAdd(self, modelName, fieldName, index=None):
        mm = self.collection().models
        model = self.getModel(modelName)

        # only adds the field if it doesn't already exist
        fieldMap = mm.field_map(model)
        if fieldName not in fieldMap:
            field = mm.new_field(fieldName)
            mm.addField(model, field)

        # repositions, even if the field already exists
        if index is not None:
            fieldMap = mm.field_map(model)
            newField = fieldMap[fieldName][1]
            mm.reposition_field(model, newField, index)

        self.save_model(mm, model)


    @util.api()
    def modelFieldRemove(self, modelName, fieldName):
        mm = self.collection().models
        model = self.getModel(modelName)
        field = self.getField(model, fieldName)

        mm.remove_field(model, field)

        self.save_model(mm, model)


    @util.api()
    def modelFieldSetFont(self, modelName, fieldName, font):
        mm = self.collection().models
        model = self.getModel(modelName)
        field = self.getField(model, fieldName)

        if not isinstance(font, str):
            raise Exception('font should be a string: {}'.format(font))

        field['font'] = font

        self.save_model(mm, model)


    @util.api()
    def modelFieldSetFontSize(self, modelName, fieldName, fontSize):
        mm = self.collection().models
        model = self.getModel(modelName)
        field = self.getField(model, fieldName)

        if not isinstance(fontSize, int):
            raise Exception('fontSize should be an integer: {}'.format(fontSize))

        field['size'] = fontSize

        self.save_model(mm, model)


    @util.api()
    def modelFieldSetDescription(self, modelName, fieldName, description):
        mm = self.collection().models
        model = self.getModel(modelName)
        field = self.getField(model, fieldName)

        if not isinstance(description, str):
            raise Exception('description should be a string: {}'.format(description))

        if 'description' in field: # older versions do not have the 'description' key
            field['description'] = description
            self.save_model(mm, model)
            return True
        return False


    @util.api()
    def deckNameFromId(self, deckId):
        deck = self.collection().decks.get(deckId)
        if deck is None:
            raise Exception('deck was not found: {}'.format(deckId))

        return deck['name']


    @util.api()
    def findNotes(self, query=None):
        if query is None:
            return []

        return list(map(int, self.collection().find_notes(query)))


    @util.api()
    def findCards(self, query=None):
        if query is None:
            return []

        return list(map(int, self.collection().find_cards(query)))


    @util.api()
    def cardsInfo(self, cards):
        result = []
        for cid in cards:
            try:
                card = self.getCard(cid)
                model = card.note_type()
                note = card.note()
                fields = {}
                for info in model['flds']:
                    order = info['ord']
                    name = info['name']
                    fields[name] = {'value': note.fields[order], 'order': order}
                states = self.collection()._backend.get_scheduling_states(card.id)
                nextReviews = self.collection()._backend.describe_next_states(states)

                result.append({
                    'cardId': card.id,
                    'fields': fields,
                    'fieldOrder': card.ord,
                    'question': util.cardQuestion(card),
                    'answer': util.cardAnswer(card),
                    'modelName': model['name'],
                    'ord': card.ord,
                    'deckName': self.deckNameFromId(card.did),
                    'css': model['css'],
                    'factor': card.factor,
                    #This factor is 10 times the ease percentage,
                    # so an ease of 310% would be reported as 3100
                    'interval': card.ivl,
                    'note': card.nid,
                    'type': card.type,
                    'queue': card.queue,
                    'due': card.due,
                    'reps': card.reps,
                    'lapses': card.lapses,
                    'left': card.left,
                    'mod': card.mod,
                    'nextReviews': list(nextReviews),
                    'flags': card.flags,
                })
            except NotFoundError:
                # Anki will give a NotFoundError if the card ID does not exist.
                # Best behavior is probably to add an 'empty card' to the
                # returned result, so that the items of the input and return
                # lists correspond.
                result.append({})

        return result

    @util.api()
    def cardsModTime(self, cards):
        result = []
        for cid in cards:
            try:
                card = self.getCard(cid)
                result.append({
                    'cardId': card.id,
                    'mod': card.mod,
                })
            except NotFoundError:
                # Anki will give a NotFoundError if the card ID does not exist.
                # Best behavior is probably to add an 'empty card' to the
                # returned result, so that the items of the input and return
                # lists correspond.
                result.append({})
        return result

    @util.api()
    def forgetCards(self, cards):
        self.startEditing()
        request = ScheduleCardsAsNew(
            card_ids=cards,
            log=True,
            restore_position=True,
            reset_counts=False,
            context=None,
        )
        self.collection()._backend.schedule_cards_as_new(request)

    @util.api()
    def relearnCards(self, cards):
        self.startEditing()
        scids = anki.utils.ids2str(cards)
        self.collection().db.execute('update cards set type=3, queue=1 where id in ' + scids)


    @util.api()
    def answerCards(self, answers):
        scheduler = self.scheduler()
        success = []
        for answer in answers:
            try:
                cid = answer['cardId']
                ease = answer['ease']
                card = self.getCard(cid)
                card.start_timer()
                scheduler.answerCard(card, ease)
                success.append(True)
            except NotFoundError:
                success.append(False)

        return success


    @util.api()
    def cardReviews(self, deck, startID):
        return self.database().all(
            'select id, cid, usn, ease, ivl, lastIvl, factor, time, type from revlog ''where id>? and cid in (select id from cards where did=?)',
            startID,
            self.decks().id(deck)
        )


    @util.api()
    def getReviewsOfCards(self, cards):
        COLUMNS = ['cid', 'id', 'usn', 'ease', 'ivl', 'lastIvl', 'factor', 'time', 'type']

        cid_to_reviews = {}
        # 999 is the maximum number of variables sqlite allows
        for cid_batch in util.batched(cards, 999):
            placeholders = ','.join('?' * len(cid_batch))

            cid_reviews = self.collection().db.all('select {} from revlog where cid in ({})'.format(', '.join(COLUMNS), placeholders), *cid_batch)
            for cid_review in cid_reviews:
                cid = cid_review[0]
                reviews = cid_to_reviews.get(cid, [])
                reviews.append(cid_review[1:])
                cid_to_reviews[cid] = reviews

        result = {}
        for card in cards:
            result[card] = [dict(zip(COLUMNS[1:], review)) for review in cid_to_reviews.get(card, [])]

        return result


    @util.api()
    def setDueDate(self, cards, days):
        self.scheduler().set_due_date(cards, days, config_key=None)
        return True


    @util.api()
    def reloadCollection(self):
        self.collection().reset()


    @util.api()
    def getLatestReviewID(self, deck):
        return self.database().scalar(
            'select max(id) from revlog where cid in (select id from cards where did=?)',
            self.decks().id(deck)
        ) or 0


    @util.api()
    def insertReviews(self, reviews):
        if len(reviews) > 0:
            sql = 'insert into revlog(id,cid,usn,ease,ivl,lastIvl,factor,time,type) values '
            for row in reviews:
                sql += '(%s),' % ','.join(map(str, row))
            sql = sql[:-1]
            self.database().execute(sql)


    @util.api()
    def notesInfo(self, notes=None, query=None):
        if notes is None and query is None:
            raise Exception('Must provide either "notes" or a "query"')
        
        if query is not None:
            notes = self.findNotes(query)

        nid_to_card_ids = {}
        # 999 is the maximum number of variables sqlite allows
        for nid_batch in util.batched(notes, 999):
            placeholders = ','.join('?' * len(nid_batch))

            cid_and_nids = self.collection().db.all('select id, nid from cards where nid in ({}) order by ord'.format(placeholders), *nid_batch)
            for cid, nid in cid_and_nids:
                card_ids = nid_to_card_ids.get(nid, [])
                card_ids.append(cid)
                nid_to_card_ids[nid] = card_ids

        result = []
        for nid in notes:
            try:
                note = self.getNote(nid)
                model = note.note_type()

                fields = {}
                for info in model['flds']:
                    order = info['ord']
                    name = info['name']
                    fields[name] = {'value': note.fields[order], 'order': order}

                result.append({
                    'noteId': note.id,
                    'profile': self.window().pm.name,
                    'tags' : note.tags,
                    'fields': fields,
                    'modelName': model['name'],
                    'mod': note.mod,
                    'cards': nid_to_card_ids[nid],
                })
            except NotFoundError:
                # Anki will give a NotFoundError if the note ID does not exist.
                # Best behavior is probably to add an 'empty card' to the
                # returned result, so that the items of the input and return
                # lists correspond.
                result.append({})

        return result

    @util.api()
    def notesModTime(self, notes):
        result = []
        for nid in notes:
            try:
                note = self.getNote(nid)
                result.append({
                    'noteId': note.id,
                    'mod': note.mod
                })
            except NotFoundError:
                # Anki will give a NotFoundError if the note ID does not exist.
                # Best behavior is probably to add an 'empty card' to the
                # returned result, so that the items of the input and return
                # lists correspond.
                result.append({})
        return result

    @util.api()
    def deleteNotes(self, notes):
        self.collection().remove_notes(notes)


    @util.api()
    def removeEmptyNotes(self):
        for model in self.collection().models.all():
            if self.collection().models.use_count(model) == 0:
                self.collection().models.remove(model["id"])
        self.window().requireReset()


    @util.api()
    def cardsToNotes(self, cards):
        return self.collection().db.list('select distinct nid from cards where id in ' + anki.utils.ids2str(cards))


    @util.api()
    def guiBrowse(self, query=None, reorderCards=None):
        browser = aqt.dialogs.open('Browser', self.window())
        browser.activateWindow()

        if query is not None:
            browser.form.searchEdit.lineEdit().setText(query)
            if hasattr(browser, 'onSearch'):
                browser.onSearch()
            else:
                browser.onSearchActivated()

        if reorderCards is not None:
            if not isinstance(reorderCards, dict):
                raise Exception('reorderCards should be a dict: {}'.format(reorderCards))
            if not ('columnId' in reorderCards and 'order' in reorderCards):
                raise Exception('Must provide a "columnId" and a "order" property"')

            cardOrder = reorderCards['order']
            if cardOrder not in ('ascending', 'descending'):
                raise Exception('invalid card order: {}'.format(reorderCards['order']))

            cardOrder = Qt.SortOrder.DescendingOrder if cardOrder == 'descending' else Qt.SortOrder.AscendingOrder
            columnId = browser.table._model.active_column_index(reorderCards['columnId'])
            if columnId == None:
                raise Exception('invalid columnId: {}'.format(reorderCards['columnId']))

            browser.table._on_sort_column_changed(columnId, cardOrder)

        return self.findCards(query)


    @util.api()
    def guiEditNote(self, note):
        Edit.open_dialog_and_show_note_with_id(note)

    @util.api()
    def guiSelectNote(self, note):
        print('guiSelectNote actually selects card IDs and is deprecated; use guiSelectCard')
        return self.guiSelectCard(note)

    @util.api()
    def guiSelectCard(self, card):
        (creator, instance) = aqt.dialogs._dialogs['Browser']
        if instance is None:
            return False
        instance.table.clear_selection()
        instance.table.select_single_card(card)
        return True

    @util.api()
    def guiSelectedNotes(self):
        (creator, instance) = aqt.dialogs._dialogs['Browser']
        if instance is None:
            return []
        return instance.selectedNotes()

    @util.api()
    def guiAddCards(self, note=None):
        if note is not None:
            collection = self.collection()

            deck = collection.decks.by_name(note['deckName'])
            if deck is None:
                raise Exception('deck was not found: {}'.format(note['deckName']))

            collection.decks.select(deck['id'])
            savedMid = deck.pop('mid', None)

            model = collection.models.by_name(note['modelName'])
            if model is None:
                raise Exception('model was not found: {}'.format(note['modelName']))

            collection.models.set_current(model)
            collection.models.update(model)

            ankiNote = anki.notes.Note(collection, model)

            # fill out card beforehand, so we can be sure of the note id
            if 'fields' in note:
                for name, value in note['fields'].items():
                    if name in ankiNote:
                        ankiNote[name] = value

            self.addMediaFromNote(ankiNote, note)

            if 'tags' in note:
                ankiNote.tags = note['tags']

            def openNewWindow():
                nonlocal ankiNote

                addCards = aqt.dialogs.open('AddCards', self.window())

                if savedMid:
                    deck['mid'] = savedMid

                addCards.editor.set_note(ankiNote)

                addCards.activateWindow()

                aqt.dialogs.open('AddCards', self.window())
                addCards.setAndFocusNote(addCards.editor.note)

            currentWindow = aqt.dialogs._dialogs['AddCards'][1]

            if currentWindow is not None:
                currentWindow.closeWithCallback(openNewWindow)
            else:
                openNewWindow()

            return ankiNote.id

        else:
            addCards = aqt.dialogs.open('AddCards', self.window())
            addCards.activateWindow()

            return addCards.editor.note.id


    @util.api()
    def guiReviewActive(self):
        return self.reviewer().card is not None and self.window().state == 'review'


    @util.api()
    def guiCurrentCard(self):
        if not self.guiReviewActive():
            raise Exception('Gui review is not currently active.')

        reviewer = self.reviewer()
        card = reviewer.card
        model = card.note_type()
        note = card.note()

        fields = {}
        for info in model['flds']:
            order = info['ord']
            name = info['name']
            fields[name] = {'value': note.fields[order], 'order': order}

        buttonList = reviewer._answerButtonList()
        return {
            'cardId': card.id,
            'fields': fields,
            'fieldOrder': card.ord,
            'question': util.cardQuestion(card),
            'answer': util.cardAnswer(card),
            'buttons': [b[0] for b in buttonList],
            'nextReviews': [reviewer.mw.col.sched.nextIvlStr(reviewer.card, b[0], True) for b in buttonList],
            'modelName': model['name'],
            'deckName': self.deckNameFromId(card.did),
            'css': model['css'],
            'template': card.template()['name']
        }


    @util.api()
    def guiStartCardTimer(self):
        if not self.guiReviewActive():
            return False

        card = self.reviewer().card
        if card is not None:
            card.startTimer()
            return True

        return False


    @util.api()
    def guiShowQuestion(self):
        if self.guiReviewActive():
            self.reviewer()._showQuestion()
            return True

        return False


    @util.api()
    def guiShowAnswer(self):
        if self.guiReviewActive():
            self.window().reviewer._showAnswer()
            return True

        return False


    @util.api()
    def guiAnswerCard(self, ease):
        if not self.guiReviewActive():
            return False

        reviewer = self.reviewer()
        if reviewer.state != 'answer':
            return False
        if ease <= 0 or ease > self.scheduler().answerButtons(reviewer.card):
            return False

        reviewer._answerCard(ease)
        return True


    @util.api()
    def guiUndo(self):
        self.window().undo()
        return True


    @util.api()
    def guiDeckOverview(self, name):
        collection = self.collection()
        if collection is not None:
            deck = collection.decks.by_name(name)
            if deck is not None:
                collection.decks.select(deck['id'])
                self.window().onOverview()
                return True

        return False


    @util.api()
    def guiDeckBrowser(self):
        self.window().moveToState('deckBrowser')


    @util.api()
    def guiDeckReview(self, name):
        if self.guiDeckOverview(name):
            self.window().moveToState('review')
            return True

        return False


    @util.api()
    def guiImportFile(self, path=None):
        """
        Open Import File (Ctrl+Shift+I) dialog with provided file path.
        If no path is given, the user will be prompted to select a file.
        Only supported from Anki version >=2.1.52

        path: string
            import file path, note on Windows you must use forward slashes.
        """
        if anki_version >= (2, 1, 52):
            from aqt.import_export.importing import import_file, prompt_for_file_then_import
        else:
            raise Exception('guiImportFile is only supported from Anki version >=2.1.52')

        if hasattr(Qt, 'WindowStaysOnTopHint'):
            # Qt5
            WindowOnTopFlag = Qt.WindowStaysOnTopHint
        elif hasattr(Qt, 'WindowType') and hasattr(Qt.WindowType, 'WindowStaysOnTopHint'):
            # Qt6
            WindowOnTopFlag = Qt.WindowType.WindowStaysOnTopHint
        else:
            # Unsupported, don't try to bring window to top
            WindowOnTopFlag = None

        # Bring window to top for user to review import settings.
        if WindowOnTopFlag is not None:
            try:
                # [Step 1/2] set always on top flag, show window (it stays on top for now)
                self.window().setWindowFlags(self.window().windowFlags() | WindowOnTopFlag)  
                self.window().show()
            finally:
                # [Step 2/2] clear always on top flag, show window (it doesn't stay on top anymore)
                self.window().setWindowFlags(self.window().windowFlags() & ~WindowOnTopFlag) 
                self.window().show()

        if path is None:
            prompt_for_file_then_import(self.window())
        else:
            import_file(self.window(), path)


    @util.api()
    def guiExitAnki(self):
        timer = QTimer()
        timer.timeout.connect(self.window().close)
        timer.start(1000) # 1s should be enough to allow the response to be sent.


    @util.api()
    def guiCheckDatabase(self):
        self.window().onCheckDB()
        return True


    @util.api()
    def addNotes(self, notes):
        results = []
        errs = []

        for note in notes:
            try:
                results.append(self.addNote(note))
            except Exception as e:
                # I specifically chose to continue, so we gather all the errors of all notes (ie not break)
                errs.append(str(e))

        if errs:
            # Roll back the changes so on error nothing happens
            self.deleteNotes(results)
            raise Exception(str(errs))

        return results


    @util.api()
    def canAddNotes(self, notes):
        results = []
        for note in notes:
            results.append(self.canAddNote(note))

        return results

    @util.api()
    def canAddNotesWithErrorDetail(self, notes):
        results = []
        for note in notes:
            results.append(self.canAddNoteWithErrorDetail(note))

        return results


    @util.api()
    def exportPackage(self, deck, path, includeSched=False):
        collection = self.collection()
        if collection is not None:
            deck = collection.decks.by_name(deck)
            if deck is not None:
                exporter = AnkiPackageExporter(collection)
                exporter.did = deck['id']
                exporter.includeSched = includeSched
                exporter.exportInto(path)
                return True

        return False


    @util.api()
    def importPackage(self, path):
        collection = self.collection()
        if collection is not None:
            try:
                self.startEditing()
                importer = AnkiPackageImporter(collection, path)
                importer.run()
            except:
                raise
            else:
                return True

        return False


    @util.api()
    def apiReflect(self, scopes=None, actions=None):
        if not isinstance(scopes, list):
            raise Exception('scopes has invalid value')
        if not (actions is None or isinstance(actions, list)):
            raise Exception('actions has invalid value')

        cls = type(self)
        scopes2 = []
        result = {'scopes': scopes2}

        if 'actions' in scopes:
            if actions is None:
                actions = dir(cls)

            methodNames = []
            for methodName in actions:
                if not isinstance(methodName, str):
                    pass
                method = getattr(cls, methodName, None)
                if method is not None and getattr(method, 'api', False):
                    methodNames.append(methodName)

            scopes2.append('actions')
            result['actions'] = methodNames

        return result


#
# Entry
#

# when run inside Anki, `__name__` would be either numeric,
# or, if installed via `link.sh`, `AnkiConnectDev`
if __name__ != "plugin":
    if platform.system() == "Windows" and anki_version == (2, 1, 50):
        util.patch_anki_2_1_50_having_null_stdout_on_windows()

    Edit.register_with_anki()

    ac = AnkiConnect()
    ac.initLogging()
    ac.startWebServer()

```

edit.py
```
import aqt
import aqt.editor
import aqt.browser.previewer
from aqt import gui_hooks
from aqt.qt import Qt, QKeySequence, QShortcut, QCloseEvent, QMainWindow
from aqt.utils import restoreGeom, saveGeom, tooltip
from anki.errors import NotFoundError
from anki.consts import QUEUE_TYPE_SUSPENDED
from anki.utils import ids2str

from . import anki_version


# Edit dialog. Like Edit Current, but:
#   * has a Preview button to preview the cards for the note
#   * has Previous/Back buttons to navigate the history of the dialog
#   * has a Browse button to open the history in the Browser
#   * has no bar with the Close button
#
# To register in Anki's dialog system:
# > from .edit import Edit
# > Edit.register_with_anki()
#
# To (re)open (note_id is an integer):
# > Edit.open_dialog_and_show_note_with_id(note_id)


DOMAIN_PREFIX = "foosoft.ankiconnect."


def get_note_by_note_id(note_id):
    return aqt.mw.col.get_note(note_id)

def is_card_suspended(card):
    return card.queue == QUEUE_TYPE_SUSPENDED

def filter_valid_note_ids(note_ids):
    return aqt.mw.col.db.list(
        "select id from notes where id in " + ids2str(note_ids)
    )


##############################################################################


class DecentPreviewer(aqt.browser.previewer.MultiCardPreviewer):
    class Adapter:
        def get_current_card(self): raise NotImplementedError
        def can_select_previous_card(self): raise NotImplementedError
        def can_select_next_card(self): raise NotImplementedError
        def select_previous_card(self): raise NotImplementedError
        def select_next_card(self): raise NotImplementedError

    def __init__(self, adapter: Adapter):
        super().__init__(parent=None, mw=aqt.mw, on_close=lambda: None) # noqa
        self.adapter = adapter
        self.last_card_id = 0

    def card(self):
        return self.adapter.get_current_card()

    def card_changed(self):
        current_card_id = self.adapter.get_current_card().id
        changed = self.last_card_id != current_card_id
        self.last_card_id = current_card_id
        return changed

    # the check if we can select next/previous card is needed because
    # the buttons sometimes get disabled a tad too late
    # and can still be pressed by user.
    # this is likely due to Anki sometimes delaying rendering of cards
    # in order to avoid rendering them too fast?
    def _on_prev_card(self):
        if self.adapter.can_select_previous_card():
            self.adapter.select_previous_card()
            self.render_card()

    def _on_next_card(self):
        if self.adapter.can_select_next_card():
            self.adapter.select_next_card()
            self.render_card()

    def _should_enable_prev(self):
        return self.showing_answer_and_can_show_question() or \
               self.adapter.can_select_previous_card()

    def _should_enable_next(self):
        return self.showing_question_and_can_show_answer() or \
               self.adapter.can_select_next_card()

    def _render_scheduled(self):
        super()._render_scheduled()  # noqa
        self._updateButtons()

    def showing_answer_and_can_show_question(self):
        return self._state == "answer" and not self._show_both_sides

    def showing_question_and_can_show_answer(self):
        return self._state == "question"


class ReadyCardsAdapter(DecentPreviewer.Adapter):
    def __init__(self, cards):
        self.cards = cards
        self.current = 0

    def get_current_card(self):
        return self.cards[self.current]

    def can_select_previous_card(self):
        return self.current > 0

    def can_select_next_card(self):
        return self.current < len(self.cards) - 1

    def select_previous_card(self):
        self.current -= 1

    def select_next_card(self):
        self.current += 1


##############################################################################


# store note ids instead of notes, as note objects don't implement __eq__ etc
class History:
    number_of_notes_to_keep_in_history = 25

    def __init__(self):
        self.note_ids = []

    def append(self, note):
        if note.id in self.note_ids:
            self.note_ids.remove(note.id)
        self.note_ids.append(note.id)
        self.note_ids = self.note_ids[-self.number_of_notes_to_keep_in_history:]

    def has_note_to_left_of(self, note):
        return note.id in self.note_ids and note.id != self.note_ids[0]

    def has_note_to_right_of(self, note):
        return note.id in self.note_ids and note.id != self.note_ids[-1]

    def get_note_to_left_of(self, note):
        note_id = self.note_ids[self.note_ids.index(note.id) - 1]
        return get_note_by_note_id(note_id)

    def get_note_to_right_of(self, note):
        note_id = self.note_ids[self.note_ids.index(note.id) + 1]
        return get_note_by_note_id(note_id)

    def get_last_note(self):            # throws IndexError if history empty
        return get_note_by_note_id(self.note_ids[-1])

    def remove_invalid_notes(self):
        self.note_ids = filter_valid_note_ids(self.note_ids)

history = History()


# see method `find_cards` of `collection.py`
def trigger_search_for_dialog_history_notes(search_context, use_history_order):
    search_context.search = " or ".join(
        f"nid:{note_id}" for note_id in history.note_ids
    )

    if use_history_order:
        search_context.order = f"""case c.nid {
            " ".join(
                f"when {note_id} then {n}"
                for (n, note_id) in enumerate(reversed(history.note_ids))
            )
        } end asc"""


##############################################################################


# noinspection PyAttributeOutsideInit
class Edit(aqt.editcurrent.EditCurrent):
    dialog_geometry_tag = DOMAIN_PREFIX + "edit"
    dialog_registry_tag = DOMAIN_PREFIX + "Edit"
    dialog_search_tag = DOMAIN_PREFIX + "edit.history"

    # depending on whether the dialog already exists, 
    # upon a request to open the dialog via `aqt.dialogs.open()`,
    # the manager will call either the constructor or the `reopen` method
    def __init__(self, note):
        QMainWindow.__init__(self, None, Qt.WindowType.Window)
        self.form = aqt.forms.editcurrent.Ui_Dialog()
        self.form.setupUi(self)
        self.setWindowTitle("Edit")
        self.setMinimumWidth(250)
        self.setMinimumHeight(400)
        restoreGeom(self, self.dialog_geometry_tag)

        self.form.buttonBox.setVisible(False)   # hides the Close button bar
        self.setup_editor_buttons()

        self.show()
        self.bring_to_foreground()

        history.remove_invalid_notes()
        history.append(note)
        self.show_note(note)

        gui_hooks.operation_did_execute.append(self.on_operation_did_execute)
        gui_hooks.editor_did_load_note.append(self.editor_did_load_note)

    def reopen(self, note):
        history.append(note)
        self.show_note(note)
        self.bring_to_foreground()

    def cleanup(self):
        gui_hooks.editor_did_load_note.remove(self.editor_did_load_note)
        gui_hooks.operation_did_execute.remove(self.on_operation_did_execute)

        self.editor.cleanup()
        saveGeom(self, self.dialog_geometry_tag)
        aqt.dialogs.markClosed(self.dialog_registry_tag)

    def closeEvent(self, evt: QCloseEvent) -> None:
        self.editor.call_after_note_saved(self.cleanup)

    # This method (mostly) solves (at least on my Windows 10 machine) three issues
    # with window activation. Without this not even too hacky a fix,
    #   * When dialog is opened from Yomichan *for the first time* since app start,
    #     the dialog opens in background (just like Browser does),
    #     but does not flash in taskbar (unlike Browser);
    #   * When dialog is opened, closed, *then main window is focused by clicking in it*,
    #     then dialog is opened from Yomichan again, same issue as above arises;
    #   * When dialog is restored from minimized state *and main window isn't minimized*,
    #     opening the dialog from Yomichan does not reliably focus it;
    #     sometimes it opens in foreground, sometimes in background.
    # With this fix, windows nearly always appear in foreground in all three cases.
    # In the case of the first two issues, strictly speaking, the fix is not ideal:
    # the window appears in background first, and then quickly pops into foreground.
    # It is not *too* unsightly, probably, no-one will notice this;
    # still, a better solution must be possible. TODO find one!
    #
    # Note that operation systems, notably Windows, and desktop managers, may restrict
    # background applications from raising windows to prevent them from interrupting
    # what the user is currently doing. For details, see:
    # https://docs.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setforegroundwindow#remarks
    # https://doc.qt.io/qt-5/qwidget.html#activateWindow
    # https://wiki.qt.io/Technical_FAQ#QWidget_::activateWindow.28.29_-_behavior_under_windows
    def bring_to_foreground(self):
        aqt.mw.app.processEvents()
        self.activateWindow()
        self.raise_()

    #################################### hooks enabled during dialog lifecycle

    def on_operation_did_execute(self, changes, handler):
        if changes.note_text and handler is not self.editor:
            self.reload_notes_after_user_action_elsewhere()

    def editor_did_load_note(self, _editor):
        self.enable_disable_next_and_previous_buttons()

    ###################################################### load & reload notes

    # setting editor.card is required for the "Cards…" button to work properly
    def show_note(self, note):
        self.note = note
        cards = note.cards()

        self.editor.set_note(note)
        self.editor.card = cards[0] if cards else None

        if any(is_card_suspended(card) for card in cards):
            tooltip("Some of the cards associated with this note " 
                    "have been suspended", parent=self)

    def reload_notes_after_user_action_elsewhere(self):
        history.remove_invalid_notes()

        try:
            self.note.load()                    # this also updates the fields
        except NotFoundError:
            try:
                self.note = history.get_last_note()
            except IndexError:
                self.cleanup()
                return

        self.show_note(self.note)

    ################################################################## actions

    # search two times, one is to select the current note or its cards,
    # and another to show the whole history, while keeping the above selection
    # set sort column to our search tag, which:
    #  * prevents the column sort indicator from being shown
    #  * serves as a hint for us to show notes or cards in history order
    #    (user can then click on any of the column names
    #    to show history cards in the order of their choosing)
    def show_browser(self, *_):
        def search_input_select_all(hook_browser, *_):
            hook_browser.form.searchEdit.lineEdit().selectAll()
            gui_hooks.browser_did_change_row.remove(search_input_select_all)
        gui_hooks.browser_did_change_row.append(search_input_select_all)

        browser = aqt.dialogs.open("Browser", aqt.mw)
        browser.table._state.sort_column = self.dialog_search_tag  # noqa
        browser.table._set_sort_indicator()  # noqa

        browser.search_for(f"nid:{self.note.id}")
        browser.table.select_all()
        browser.search_for(self.dialog_search_tag)

    def show_preview(self, *_):
        if cards := self.note.cards():
            previewer = DecentPreviewer(ReadyCardsAdapter(cards))
            previewer.open()
            return previewer
        else:
            tooltip("No cards found", parent=self)
            return None

    def show_previous(self, *_):
        if history.has_note_to_left_of(self.note):
            self.show_note(history.get_note_to_left_of(self.note))

    def show_next(self, *_):
        if history.has_note_to_right_of(self.note):
            self.show_note(history.get_note_to_right_of(self.note))

    ################################################## button and hotkey setup

    def setup_editor_buttons(self):
        gui_hooks.editor_did_init.append(self.add_preview_button)
        gui_hooks.editor_did_init_buttons.append(self.add_right_hand_side_buttons)

        # on Anki 2.1.50, browser mode makes the Preview button visible
        extra_kwargs = {} if anki_version < (2, 1, 50) else {
            "editor_mode": aqt.editor.EditorMode.BROWSER
        }

        self.editor = aqt.editor.Editor(aqt.mw, self.form.fieldsArea, self,
                                        **extra_kwargs)

        gui_hooks.editor_did_init_buttons.remove(self.add_right_hand_side_buttons)
        gui_hooks.editor_did_init.remove(self.add_preview_button)

    # * on Anki < 2.1.50, make the button via js (`setupEditor` of browser.py);
    #   also, make a copy of _links so that opening Anki's browser does not
    #   screw them up as they are apparently shared between instances?!
    #   the last part seems to have been fixed in Anki 2.1.50
    # * on Anki 2.1.50, the button is created by setting editor mode,
    #   see above; so we only need to add the link.
    def add_preview_button(self, editor):
        QShortcut(QKeySequence("Ctrl+Shift+P"), self, self.show_preview)

        if anki_version < (2, 1, 50):
            editor._links = editor._links.copy()
            editor.web.eval("""
                $editorToolbar.then(({notetypeButtons}) => 
                    notetypeButtons.appendButton(
                        {component: editorToolbar.PreviewButton, id: 'preview'}
                    )
                );
            """)

        editor._links["preview"] = lambda _editor: self.show_preview() and None

    # * on Anki < 2.1.50, button style is okay-ish from get-go,
    #   except when disabled; adding class `btn` fixes that;
    # * on Anki 2.1.50, buttons have weird font size and are square';
    #   the style below makes them in line with left-hand side buttons
    def add_right_hand_side_buttons(self, buttons, editor):
        if anki_version < (2, 1, 50):
            extra_button_class = "btn"
        else:
            extra_button_class = "anki-connect-button"
            editor.web.eval("""
                (function(){
                    const style = document.createElement("style");
                    style.innerHTML = `
                        .anki-connect-button {
                            white-space: nowrap;
                            width: auto;
                            padding: 0 2px;
                            font-size: var(--base-font-size);
                        }
                        .anki-connect-button:disabled {
                            pointer-events: none;
                            opacity: .4;
                        }
                    `;
                    document.head.appendChild(style);
                })();
            """)

        def add(cmd, function, label, tip, keys):
            button_html = editor.addButton(
                icon=None, 
                cmd=DOMAIN_PREFIX + cmd, 
                id=DOMAIN_PREFIX + cmd,
                func=function, 
                label=f"&nbsp;&nbsp;{label}&nbsp;&nbsp;",
                tip=f"{tip} ({keys})",
                keys=keys,
            )

            button_html = button_html.replace('class="',
                                              f'class="{extra_button_class} ')
            buttons.append(button_html)

        add("browse", self.show_browser, "Browse", "Browse", "Ctrl+F")
        add("previous", self.show_previous, "&lt;", "Previous", "Alt+Left")
        add("next", self.show_next, "&gt;", "Next", "Alt+Right")

    def run_javascript_after_toolbar_ready(self, js):
        js = f"setTimeout(function() {{ {js} }}, 1)"
        if anki_version < (2, 1, 50):
            js = f'$editorToolbar.then(({{ toolbar }}) => {js})'
        else:
            js = f'require("anki/ui").loaded.then(() => {js})'
        self.editor.web.eval(js)

    def enable_disable_next_and_previous_buttons(self):
        def to_js(boolean):
            return "true" if boolean else "false"

        disable_previous = not(history.has_note_to_left_of(self.note))
        disable_next = not(history.has_note_to_right_of(self.note))

        self.run_javascript_after_toolbar_ready(f"""
            document.getElementById("{DOMAIN_PREFIX}previous")
                    .disabled = {to_js(disable_previous)};
            document.getElementById("{DOMAIN_PREFIX}next")
                    .disabled = {to_js(disable_next)};
        """)

    ##########################################################################

    @classmethod
    def browser_will_search(cls, search_context):
        if search_context.search == cls.dialog_search_tag:
            trigger_search_for_dialog_history_notes(
                search_context=search_context,
                use_history_order=cls.dialog_search_tag ==
                        search_context.browser.table._state.sort_column  # noqa
            )

    @classmethod
    def register_with_anki(cls):
        if cls.dialog_registry_tag not in aqt.dialogs._dialogs:  # noqa
            aqt.dialogs.register_dialog(cls.dialog_registry_tag, cls)
            gui_hooks.browser_will_search.append(cls.browser_will_search)

    @classmethod
    def open_dialog_and_show_note_with_id(cls, note_id):    # raises NotFoundError
        note = get_note_by_note_id(note_id)
        return aqt.dialogs.open(cls.dialog_registry_tag, note)

```

util.py
```
# Copyright 2016-2021 Alex Yatskov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import os
import sys

import anki
import anki.sync
import aqt
import enum
import itertools

#
# Utilities
#

class MediaType(enum.Enum):
    Audio = 1
    Video = 2
    Picture = 3


def download(url):
    client = anki.sync.AnkiRequestsClient()
    client.timeout = setting('webTimeout') / 1000

    resp = client.get(url)
    if resp.status_code != 200:
        raise Exception('{} download failed with return code {}'.format(url, resp.status_code))

    return client.streamContent(resp)


def api(*versions):
    def decorator(func):
        setattr(func, 'versions', versions)
        setattr(func, 'api', True)
        return func

    return decorator


def cardQuestion(card):
    if getattr(card, 'question', None) is None:
        return card._getQA()['q']

    return card.question()


def cardAnswer(card):
    if getattr(card, 'answer', None) is None:
        return card._getQA()['a']

    return card.answer()


DEFAULT_CONFIG = {
    'apiKey': None,
    'apiLogPath': None,
    'apiPollInterval': 25,
    'apiVersion': 6,
    'webBacklog': 5,
    'webBindAddress': os.getenv('ANKICONNECT_BIND_ADDRESS', '127.0.0.1'),
    'webBindPort': 8765,
    'webCorsOrigin': os.getenv('ANKICONNECT_CORS_ORIGIN', None),
    'webCorsOriginList': ['http://localhost'],
    'ignoreOriginList': [],
    'webTimeout': 10000,
}

def setting(key):
    try:
        return aqt.mw.addonManager.getConfig(__name__).get(key, DEFAULT_CONFIG[key])
    except:
        raise Exception('setting {} not found'.format(key))


# see https://github.com/FooSoft/anki-connect/issues/308
# fixed in https://github.com/ankitects/anki/commit/0b2a226d
def patch_anki_2_1_50_having_null_stdout_on_windows():
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf8")


# ref https://docs.python.org/3.12/library/itertools.html#itertools.batched
if sys.version_info >= (3, 12):
    batched = itertools.batched
else:
    def batched(iterable, n):
        iterator = iter(iterable)
        while True:
            batch = tuple(itertools.islice(iterator, n))
            if not batch:
                break
            yield batch

```

web.py
```
# Copyright 2016-2021 Alex Yatskov
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

import json
import jsonschema
import select
import socket

from . import util

#
# WebRequest
#

class WebRequest:
    def __init__(self, method, headers, body):
        self.method = method
        self.headers = headers
        self.body = body


#
# WebClient
#

class WebClient:
    def __init__(self, sock, handler):
        self.sock = sock
        self.handler = handler
        self.readBuff = bytes()
        self.writeBuff = bytes()


    def advance(self, recvSize=1024):
        if self.sock is None:
            return False

        rlist, wlist = select.select([self.sock], [self.sock], [], 0)[:2]
        self.sock.settimeout(5.0)

        if rlist:
            while True:
                try:
                    msg = self.sock.recv(recvSize)
                except (ConnectionResetError, socket.timeout):
                    self.close()
                    return False
                if not msg:
                    self.close()
                    return False
                self.readBuff += msg

                req, length = self.parseRequest(self.readBuff)
                if req is not None:
                    self.readBuff = self.readBuff[length:]
                    self.writeBuff += self.handler(req)
                    break



        if wlist and self.writeBuff:
            try:
                length = self.sock.send(self.writeBuff)
                self.writeBuff = self.writeBuff[length:]
                if not self.writeBuff:
                    self.close()
                    return False
            except:
                self.close()
                return False
        return True


    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

        self.readBuff = bytes()
        self.writeBuff = bytes()


    def parseRequest(self, data):
        parts = data.split('\r\n\r\n'.encode('utf-8'), 1)
        if len(parts) == 1:
            return None, 0

        lines = parts[0].split('\r\n'.encode('utf-8'))
        method = None

        if len(lines) > 0:
            request_line_parts = lines[0].split(' '.encode('utf-8'))
            method = request_line_parts[0].upper() if len(request_line_parts) > 0 else None

        headers = {}
        for line in lines[1:]:
            pair = line.split(': '.encode('utf-8'))
            headers[pair[0].lower()] = pair[1] if len(pair) > 1 else None

        headerLength = len(parts[0]) + 4
        bodyLength = int(headers.get('content-length'.encode('utf-8'), 0))
        totalLength = headerLength + bodyLength

        if totalLength > len(data):
            return None, 0

        body = data[headerLength : totalLength]
        return WebRequest(method, headers, body), totalLength

#
# WebServer
#

class WebServer:
    def __init__(self, handler):
        self.handler = handler
        self.clients = []
        self.sock = None


    def advance(self):
        if self.sock is not None:
            self.acceptClients()
            self.advanceClients()


    def acceptClients(self):
        rlist = select.select([self.sock], [], [], 0)[0]
        if not rlist:
            return

        clientSock = self.sock.accept()[0]
        if clientSock is not None:
            clientSock.setblocking(False)
            self.clients.append(WebClient(clientSock, self.handlerWrapper))


    def advanceClients(self):
        self.clients = list(filter(lambda c: c.advance(), self.clients))


    def listen(self):
        self.close()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setblocking(False)
        self.sock.bind((util.setting('webBindAddress'), util.setting('webBindPort')))
        self.sock.listen(util.setting('webBacklog'))


    def handlerWrapper(self, req):
        allowed, corsOrigin = self.allowOrigin(req)

        if req.method == b'OPTIONS':
            body = ''.encode('utf-8')
            headers = self.buildHeaders(corsOrigin, body)

            if b'access-control-request-private-network' in req.headers and (
            req.headers[b'access-control-request-private-network'] == b'true'):
                # include this header so that if a public origin is included in the whitelist,
                # then browsers won't fail requests due to the private network access check
                headers.append(['Access-Control-Allow-Private-Network', 'true'])

            return self.buildResponse(headers, body)
    
        try:
            params = json.loads(req.body.decode('utf-8'))
            jsonschema.validate(params, request_schema)
        except (ValueError, jsonschema.ValidationError) as e:
            if allowed:
                if len(req.body) == 0:
                    body = json.dumps({"apiVersion": f"AnkiConnect v.{util.setting('apiVersion')}"}).encode('utf-8')
                else:
                    reply = format_exception_reply(util.setting('apiVersion'), e)
                    body = json.dumps(reply).encode('utf-8')
                headers = self.buildHeaders(corsOrigin, body)
                return self.buildResponse(headers, body)
            else:
                params = {}  # trigger the 403 response below

        if allowed or params.get('action', '') == 'requestPermission':
            if params.get('action', '') == 'requestPermission':
                params['params'] = params.get('params', {})
                params['params']['allowed'] = allowed
                params['params']['origin'] = b'origin' in req.headers and req.headers[b'origin'].decode() or ''
                if not allowed :
                    corsOrigin = params['params']['origin']
                        
            body = json.dumps(self.handler(params)).encode('utf-8')
            headers = self.buildHeaders(corsOrigin, body)
        else :
            headers = [
                ['HTTP/1.1 403 Forbidden', None],
                ['Access-Control-Allow-Origin', corsOrigin],
                ['Access-Control-Allow-Headers', '*']
            ]
            body = ''.encode('utf-8')

        return self.buildResponse(headers, body)


    def allowOrigin(self, req):
        # handle multiple cors origins by checking the 'origin'-header against the allowed origin list from the config
        webCorsOriginList = util.setting('webCorsOriginList')

        # keep support for deprecated 'webCorsOrigin' field, as long it is not removed
        webCorsOrigin = util.setting('webCorsOrigin')
        if webCorsOrigin:
            webCorsOriginList.append(webCorsOrigin)

        allowed = False
        corsOrigin = 'http://localhost'
        allowAllCors = '*' in webCorsOriginList  # allow CORS for all domains
        
        if allowAllCors:
            corsOrigin = '*'
            allowed = True
        elif b'origin' in req.headers:
            originStr = req.headers[b'origin'].decode()
            if originStr in webCorsOriginList :
                corsOrigin = originStr
                allowed = True
            elif 'http://localhost' in webCorsOriginList and ( 
            originStr == 'http://127.0.0.1' or originStr == 'https://127.0.0.1' or # allow 127.0.0.1 if localhost allowed
            originStr.startswith('http://127.0.0.1:') or originStr.startswith('http://127.0.0.1:') or
            originStr.startswith('chrome-extension://') or originStr.startswith('moz-extension://') or originStr.startswith('safari-web-extension://') ) : # allow chrome, firefox and safari extension if localhost allowed
                corsOrigin = originStr
                allowed = True
        else:
            allowed = True
        
        return allowed, corsOrigin
    

    def buildHeaders(self, corsOrigin, body):
        return [
            ['HTTP/1.1 200 OK', None],
            ['Content-Type', 'application/json'],
            ['Access-Control-Allow-Origin', corsOrigin],
            ['Access-Control-Allow-Headers', '*'],
            ['Content-Length', str(len(body))]
        ]


    def buildResponse(self, headers, body):
        resp = bytes()
        for key, value in headers:
            if value is None:
                resp += '{}\r\n'.format(key).encode('utf-8')
            else:
                resp += '{}: {}\r\n'.format(key, value).encode('utf-8')

        resp += '\r\n'.encode('utf-8')
        resp += body
        return resp


    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None

        for client in self.clients:
            client.close()

        self.clients = []


def format_success_reply(api_version, result):
    if api_version <= 4:
        return result
    else:
        return {"result": result, "error": None}


def format_exception_reply(_api_version, exception):
    return {"result": None, "error": str(exception)}


request_schema = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "minLength": 1},
        "version": {"type": "integer"},
        "params": {"type": "object"},
    },
    "required": ["action"],
}

```
